from __future__ import annotations

import base64
import json
import re
import time
import uuid
from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx
from pydantic import ValidationError

from ..contracts.camera import CameraFrame
from ..contracts.task_intent import TaskIntent
from .prompts import TASK_UNDERSTANDING_PROMPT, VISION_GROUNDING_PROMPT, SKILL_PLANNING_PROMPT, prompt_payload
from .skill_planning import SkillPlanningRequest, SkillPlanLLMOutput
from .task_understanding import TaskParseOutput, TaskUnderstandingRequest
from .vision_grounding import VisionEntity, VisionGroundingOutput


class QwenProviderError(RuntimeError):
    def __init__(self, message, *, code="provider_error"):
        super().__init__(message)
        self.code = code


class QwenHTTPProvider:
    """OpenAI-compatible Qwen adapter with strict Brain contracts."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        structured_output: bool = True,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        planner_max_completion_tokens: int = 1024,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.structured_output = structured_output
        self.planner_max_completion_tokens = planner_max_completion_tokens
        if client is not None and transport is not None:
            raise ValueError("supply either client or transport")
        self.client, self.transport = client, transport
        self.calls: list[dict[str, Any]] = []
        self.last_raw_values: dict[str, Any] = {}
        self.last_raw_text: dict[str, str] = {}

    def _redact(self, text):
        return text.replace(self.api_key, "[REDACTED]") if self.api_key else text

    def _call(self, stage: str, prompt: str, content, schema: dict[str, Any], parse=None, *, max_completion_tokens=None):
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        }
        if max_completion_tokens is not None:
            payload["max_completion_tokens"] = max_completion_tokens
        if self.structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": stage, "strict": True, "schema": schema},
            }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        request_id = uuid.uuid4().hex
        headers["X-Request-ID"] = request_id
        url = urlsplit(self.base_url)
        summary_url = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        record = {"stage":stage, "status":"failed", "request_id":request_id,
                  "model":self.model, "base_url":summary_url, "finish_reason":None, "usage":None}
        started = time.monotonic()
        self.last_raw_text.pop(stage, None)
        self.last_raw_values.pop(stage, None)
        response = None
        try:
            if self.client is not None:
                response = self.client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
            else:
                with httpx.Client(transport=self.transport) as client:
                    response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
            record["http_status"] = response.status_code
            record["response_request_id"] = response.headers.get("x-request-id")
            self.last_raw_text[stage] = self._redact(response.text)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise QwenProviderError("response body must be an object")
            usage = body.get("usage")
            if isinstance(usage, dict):
                record["usage"] = {k:v for k,v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, int)}
                record.update(record["usage"])
            choice = body["choices"][0]
            record["finish_reason"] = choice.get("finish_reason")
            raw = choice["message"]["content"]
            if not isinstance(raw, str):
                raise QwenProviderError(f"{stage}: response content is not text")
            self.last_raw_text[stage] = self._redact(raw)
            if record["finish_reason"] == "length":
                raise QwenProviderError("model_output_truncated")
            value = _extract_json(raw)
            self.last_raw_values[stage] = deepcopy(value)
            result = parse(value) if parse else value
            record["status"] = "succeeded"
            return result
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, QwenProviderError) as exc:
            record["error"] = self._redact(f"{type(exc).__name__}: {exc}")
            code = str(exc) if str(exc) in {"motion_distance_evidence_missing", "motion_clause_binding_ambiguous"} else "provider_error"
            if stage == "skill_planning" and isinstance(exc, ValidationError):
                code = "planner_unknown_skill" if any(e["loc"][-1:] == ("skill",) and e["type"] == "enum" for e in exc.errors()) else "skill_plan_output_invalid"
            record["error_code"] = code
            raise QwenProviderError(f"{stage}: {record['error']}", code=code) from exc
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            self.calls.append(record)

    def understand(self, request: TaskUnderstandingRequest) -> TaskIntent:
        return self._call(
            "task_understanding",
            TASK_UNDERSTANDING_PROMPT,
            prompt_payload({"instruction": request.instruction}),
            TaskParseOutput.model_json_schema(),
            lambda value: TaskParseOutput.model_validate(value).to_task_intent(request.instruction),
        )

    def understand_turn(self, request: TaskUnderstandingRequest):
        def parse(value):
            marker = re.search(r"\[dialogue_exclude=([^\]]+)\]", request.instruction)
            if marker and value.get("entities"):
                value["entities"][0]["exclude_scene_object_ids"] = [marker.group(1)]
            return TaskParseOutput.model_validate(value).to_brain_turn(request.instruction)
        return self._call("task_understanding", TASK_UNDERSTANDING_PROMPT,
                          prompt_payload({"instruction": request.instruction}), TaskParseOutput.model_json_schema(), parse)

    def plan(self, request: SkillPlanningRequest) -> SkillPlanLLMOutput:
        content = {**request.context.model_dump(mode="json"), "skills": request.skill_catalog}
        budget = min(self.planner_max_completion_tokens, 384 + 128 * max(len(request.context.operations), 1))
        return self._call("skill_planning", SKILL_PLANNING_PROMPT, prompt_payload(content),
                          SkillPlanLLMOutput.model_json_schema(), SkillPlanLLMOutput.model_validate,
                          max_completion_tokens=budget)

    def detect(self, frame: CameraFrame, entities: list[VisionEntity]) -> VisionGroundingOutput:
        if frame.rgb is None:
            raise QwenProviderError("vision_grounding: RGB frame is missing")
        content = [
            {"type": "text", "text": prompt_payload({"entities": [item.model_dump(mode="json") for item in entities]})},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(frame.rgb).decode('ascii')}"}},
        ]
        return self._call(
            "vision_grounding",
            VISION_GROUNDING_PROMPT,
            content,
            VisionGroundingOutput.model_json_schema(),
            VisionGroundingOutput.model_validate,
        )


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        if not text.endswith("```"):
            raise QwenProviderError("unterminated JSON fence")
        text = text[3:].strip()
        if text.startswith("json"):
            text = text[4:].lstrip()
        text = text[:-3].rstrip()
    decoder = json.JSONDecoder()
    value, end = decoder.raw_decode(text)
    if not isinstance(value, dict) or text[end:].strip():
        raise QwenProviderError("model output must be exactly one JSON object")
    return value

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from ..contracts.camera import CameraFrame
from ..contracts.task_intent import TaskIntent
from .prompts import TASK_UNDERSTANDING_PROMPT, VISION_GROUNDING_PROMPT, prompt_payload
from .task_understanding import TaskParseOutput, TaskUnderstandingRequest
from .vision_grounding import VisionEntity, VisionGroundingOutput


class QwenProviderError(RuntimeError):
    pass


class QwenHTTPProvider:
    """OpenAI-compatible Qwen adapter with strict Brain contracts."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        structured_output: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.structured_output = structured_output
        self.calls: list[dict[str, Any]] = []

    def _call(self, stage: str, prompt: str, content, schema: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        }
        if self.structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": stage, "strict": True, "schema": schema},
            }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = None
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            raw = body["choices"][0]["message"]["content"]
            if not isinstance(raw, str):
                raise QwenProviderError(f"{stage}: response content is not text")
            value = _extract_json(raw)
            usage = body.get("usage", {})
            self.calls.append({"stage": stage, "status": "succeeded", **usage})
            return value
        except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self.calls.append({
                "stage": stage,
                "status": "failed",
                "http_status": getattr(response, "status_code", None),
                "error": str(exc),
            })
            raise QwenProviderError(f"{stage}: {type(exc).__name__}: {exc}") from exc

    def understand(self, request: TaskUnderstandingRequest) -> TaskIntent:
        value = self._call(
            "task_understanding",
            TASK_UNDERSTANDING_PROMPT,
            prompt_payload({"instruction": request.instruction}),
            TaskParseOutput.model_json_schema(),
        )
        return TaskParseOutput.model_validate(value).to_task_intent(request.instruction)

    def understand_turn(self, request: TaskUnderstandingRequest):
        value = self._call("task_understanding", TASK_UNDERSTANDING_PROMPT, prompt_payload({"instruction": request.instruction}), TaskParseOutput.model_json_schema())
        return TaskParseOutput.model_validate(value).to_brain_turn(request.instruction)

    def detect(self, frame: CameraFrame, entities: list[VisionEntity]) -> VisionGroundingOutput:
        if frame.rgb is None:
            raise QwenProviderError("vision_grounding: RGB frame is missing")
        content = [
            {"type": "text", "text": prompt_payload({"entities": [item.model_dump(mode="json") for item in entities]})},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(frame.rgb).decode('ascii')}"}},
        ]
        value = self._call(
            "vision_grounding",
            VISION_GROUNDING_PROMPT,
            content,
            VisionGroundingOutput.model_json_schema(),
        )
        return VisionGroundingOutput.model_validate(value)


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

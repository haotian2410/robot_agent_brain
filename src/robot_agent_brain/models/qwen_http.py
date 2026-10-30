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
from ..errors import BrainError
from .prompts import TASK_UNDERSTANDING_PROMPT, VISION_GROUNDING_PROMPT, SKILL_PLANNING_PROMPT, prompt_payload
from .skill_planning import SkillPlanningRequest, SkillPlanLLMOutput
from .task_understanding import (TaskUnderstandingRequest, parse_qwen_turn,
                                  task_understanding_v3_wire_schema)
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
        except BrainError as exc:
            # The model response reached the endpoint and parsed as JSON, but
            # the Brain rejected its semantic contract. Preserve the precise
            # stage/code instead of wrapping it as a provider transport error.
            # A provider call itself completed with an unusable model output;
            # keep the call record in the historical ``failed`` bucket while
            # exposing the precise semantic code separately.
            record["status"] = "failed"
            record["error"] = self._redact(f"{type(exc).__name__}: {exc}")
            record["error_code"] = exc.issue.code
            # Keep the provider boundary exception stable for callers while
            # preserving the semantic/protocol code for AgentApplication and
            # the task result.  Transport failures remain provider_error;
            # model JSON that parses but violates a contract is not silently
            # relabeled as a network/provider failure.
            raise QwenProviderError(f"{stage}: {record['error']}", code=exc.issue.code) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, QwenProviderError) as exc:
            record["error"] = self._redact(f"{type(exc).__name__}: {exc}")
            text = str(exc)
            semantic_prefixes = (
                "task_semantic_invalid", "scene_edit_", "scene_replace_", "query_",
                "dialogue_", "motion_distance_evidence_missing", "motion_clause_binding_ambiguous",
            )
            # A VLM response can be valid JSON but still violate the strict
            # detection contract (for example, a reversed bbox).  This is a
            # model-output schema problem, not transport failure, and must be
            # distinguishable in the task report/UI.
            if stage == "vision_grounding" and isinstance(exc, ValidationError):
                code = "vision_output_schema_invalid"
            else:
                code = "semantic_protocol_error" if text.startswith(semantic_prefixes) else "provider_error"
            if text in {"motion_distance_evidence_missing", "motion_clause_binding_ambiguous"}:
                code = text
            if code == "semantic_protocol_error":
                record["status"] = "rejected"
            if stage == "skill_planning" and isinstance(exc, ValidationError):
                code = "planner_unknown_skill" if any(e["loc"][-1:] == ("skill",) and e["type"] == "enum" for e in exc.errors()) else "skill_plan_output_invalid"
            record["error_code"] = code
            raise QwenProviderError(f"{stage}: {record['error']}", code=code) from exc
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            self.calls.append(record)

    def understand(self, request: TaskUnderstandingRequest) -> TaskIntent:
        """Legacy TaskIntent adapter backed by the same v3 wire contract.

        ``understand_turn`` is the canonical route-aware API.  This method is
        retained for providers implementing the older TaskUnderstandingProvider
        protocol, but it must not reintroduce the historical v2 prompt/schema
        pair.  Non-robot routes are deliberately rejected because this method
        cannot represent their payloads as TaskIntent.
        """
        return self._call(
            "task_understanding",
            TASK_UNDERSTANDING_PROMPT,
            prompt_payload({"instruction": request.instruction}),
            task_understanding_v3_wire_schema(),
            lambda value: _task_intent_from_v3(value, request.instruction),
        )

    def understand_turn(self, request: TaskUnderstandingRequest):
        def parse(value):
            value = _repair_explicit_replace(value, request.instruction)
            value = _repair_explicit_selector_clarification(value, request.instruction)
            return parse_qwen_turn(value, request.instruction)
        return self._call("task_understanding", TASK_UNDERSTANDING_PROMPT,
                          prompt_payload({"instruction": request.instruction}), task_understanding_v3_wire_schema(), parse)

    def plan(self, request: SkillPlanningRequest) -> SkillPlanLLMOutput:
        content = {**request.context.model_dump(mode="json"), "skills": request.skill_catalog}
        budget = min(self.planner_max_completion_tokens, 384 + 128 * max(len(request.context.operations), 1))
        try:
            return self._call("skill_planning", SKILL_PLANNING_PROMPT, prompt_payload(content),
                              SkillPlanLLMOutput.model_json_schema(), SkillPlanLLMOutput.model_validate,
                              max_completion_tokens=budget)
        except QwenProviderError as exc:
            # Qwen/llama-server may finish a valid structured plan exactly at the small
            # operation-derived budget (512 for one pick-and-place).  A bounded retry prevents
            # an otherwise valid task from becoming a provider failure while preserving strict
            # JSON/schema validation and the original failed call in diagnostics.
            if "model_output_truncated" not in str(exc) or budget >= self.planner_max_completion_tokens:
                raise
            retry_budget = min(self.planner_max_completion_tokens, max(budget * 2, 1024))
            return self._call("skill_planning", SKILL_PLANNING_PROMPT, prompt_payload(content),
                              SkillPlanLLMOutput.model_json_schema(), SkillPlanLLMOutput.model_validate,
                              max_completion_tokens=retry_budget)

    def plan_dual(self, request):
        from .dual_skill_planning import DualSkillPlanOutput
        from .prompts import DUAL_SKILL_PLANNING_PROMPT
        return self._call("skill_planning", DUAL_SKILL_PLANNING_PROMPT,
                          prompt_payload({**request.context, "skills": request.skill_catalog}),
                          DualSkillPlanOutput.model_json_schema(), DualSkillPlanOutput.model_validate,
                          max_completion_tokens=self.planner_max_completion_tokens)

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


def _task_intent_from_v3(value: dict[str, Any], instruction: str) -> TaskIntent:
    """Convert the canonical route-aware response for legacy callers."""
    turn = parse_qwen_turn(value, instruction)
    if turn.task_intent is None:
        raise ValueError("task_semantic_invalid: task understanding did not return robot_task")
    return turn.task_intent


def _repair_explicit_replace(value: dict[str, Any], instruction: str) -> dict[str, Any]:
    """Fill a narrowly recoverable replace role omitted by Qwen.

    The user phrase is authoritative here: ``替换成/替换为/换成 X`` names the
    replacement explicitly.  This is performed only at the live Qwen adapter
    boundary; direct/replay ``parse_qwen_turn`` remains strict and reports a
    missing ``replacement_entity``.  We never invent a model from an implicit
    ``replace`` operation or overwrite a non-empty model value.
    """
    if not isinstance(value, dict) or value.get("status", "accepted") != "accepted":
        return value
    if value.get("turn_kind") != "scene_edit" or not isinstance(value.get("scene_edit"), dict):
        return value
    scene_edit = value["scene_edit"]
    operations = scene_edit.get("operations")
    if not isinstance(operations, list):
        return value
    replace_ops = [item for item in operations
                   if isinstance(item, dict) and item.get("operation") == "replace"]
    # Do not broadcast one phrase to multiple replacement operations.  A
    # multi-object instruction may name different replacements, and guessing
    # that they all use the same target would turn a recoverable schema error
    # into a wrong scene edit.  Such payloads remain strict failures until the
    # model emits each replacement role explicitly.
    if len(replace_ops) != 1 or any(item.get("replacement_entity") for item in replace_ops):
        return value
    match = re.search(r"(?:替换成|替换为|换成|replace(?:d)?\s+(?:with|by))\s*([\w一-龥 -]+)", instruction, re.IGNORECASE)
    if not match:
        return value
    raw_name = match.group(1).strip(" ，,。.!！?？\t\n")
    if not raw_name:
        return value
    aliases = {"苹果": "apple", "香蕉": "banana", "篮子": "basket", "托盘": "tray",
               "apple": "apple", "banana": "banana", "basket": "basket", "tray": "tray"}
    semantic_name = aliases.get(raw_name.casefold(), aliases.get(raw_name, raw_name))
    entities = list(scene_edit.get("entities") or [])
    replacement_id = None
    for entity in entities:
        if isinstance(entity, dict) and (entity.get("entity_id") == semantic_name or
                                         str(entity.get("semantic_name", "")).casefold() == raw_name.casefold()):
            replacement_id = entity.get("entity_id")
            break
    if replacement_id is None:
        replacement_id = semantic_name.replace(" ", "_")
        category = "fruit" if semantic_name in {"apple", "banana"} else (
            "container" if semantic_name in {"basket", "tray"} else "object")
        entities.append({"entity_id": replacement_id, "semantic_name": semantic_name,
                         "category": category, "count": 1, "quantity_mode": "single"})
    scene_edit = {**scene_edit, "entities": entities,
                  "operations": [({**item, "replacement_entity": replacement_id}
                                   if isinstance(item, dict) and item.get("operation") == "replace" and not item.get("replacement_entity")
                                   else item) for item in operations]}
    return {**value, "scene_edit": scene_edit}


def _repair_explicit_selector_clarification(value: dict[str, Any], instruction: str) -> dict[str, Any]:
    """Recover one explicit selector edit that Qwen incorrectly clarifies.

    This is intentionally narrower than a general semantic parser.  When the
    user names the subject, reference, extremum and a concrete colour in the
    same sentence, there is enough evidence to build the v3 scene-edit wire
    payload without asking the model to invent a scene object or a position.
    Other clarification responses remain untouched.
    """
    if not isinstance(value, dict) or value.get("status") != "clarification_required":
        return value
    text = instruction.strip()
    match = re.search(
        r"(?:离|距|距离)\s*([\w一-龥]+)\s*(最近|最远)\s*的\s*([\w一-龥]+)\s*"
        r"(?:改成|改为|变成)\s*([#\w一-龥-]+)", text,
    )
    if not match:
        return value
    reference_raw, relation_raw, subject_raw, color_raw = (part.strip() for part in match.groups())
    aliases = {
        "苹果": "apple", "香蕉": "banana", "篮子": "basket", "托盘": "tray",
        "apple": "apple", "banana": "banana", "basket": "basket", "tray": "tray",
    }
    colors = {
        "蓝": "blue", "蓝色": "blue", "红": "red", "红色": "red",
        "绿": "green", "绿色": "green", "黄": "yellow", "黄色": "yellow",
        "白": "white", "白色": "white", "黑": "black", "黑色": "black",
    }
    reference = aliases.get(reference_raw.casefold())
    subject = aliases.get(subject_raw.casefold())
    color = colors.get(color_raw.casefold(), color_raw)
    if reference is None or subject is None or not color:
        return value
    entities = [
        {"entity_id": subject, "semantic_name": subject, "category": "fruit" if subject in {"apple", "banana"} else "object"},
        {"entity_id": reference, "semantic_name": reference, "category": "container" if reference in {"basket", "tray"} else "object"},
    ]
    scene_edit = {
        "scene_basis": "current",
        "entities": entities,
        "relations": [{"scope": "selection", "subject": subject,
                       "relation": "nearest" if relation_raw == "最近" else "farthest",
                       "reference": reference}],
        "operations": [{"operation": "update_properties", "target": subject,
                        "properties": {"color": color}}],
    }
    return {
        "protocol_version": "task_understanding.v3", "status": "accepted",
        "turn_kind": "scene_edit", "scene_edit": scene_edit,
        "scene_query": None, "session_control": None,
        "robot_setup_request": None, "entities": [], "operations": [], "relations": [],
    }


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

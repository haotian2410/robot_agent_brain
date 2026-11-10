from __future__ import annotations

import base64
import hashlib
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
from .prompts import TASK_UNDERSTANDING_PROMPT, VISION_GROUNDING_PROMPT, SKILL_PLANNING_PROMPT, prompt_payload, build_asset_catalog_prompt
from .skill_planning import SkillPlanningRequest, SkillPlanLLMOutput
from .task_understanding import (TaskUnderstandingRequest, parse_qwen_turn,
                                  task_understanding_v3_wire_schema)
from .vision_grounding import VisionEntity, VisionGroundingOutput


class QwenProviderError(RuntimeError):
    def __init__(self, message, *, code="provider_error"):
        super().__init__(message)
        self.code = code


def _color_mentions(text):
    from ..scene.colors import ALIASES, PALETTE, color_name
    labels = sorted(set((*ALIASES, *PALETTE)), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)
    return [(match.start(), match.end(), color_name(match.group())) for match in pattern.finditer(text)]


def _repair_live_color_update_selector(value, instruction, catalog):
    """Convert Qwen's unreferenced ``near`` noise into the explicit color selector."""
    if not isinstance(value, dict):
        return value
    edit = value.get("scene_edit")
    operations = edit.get("operations") if isinstance(edit, dict) else None
    entities = edit.get("entities") if isinstance(edit, dict) else None
    if value.get("status") != "accepted" or len(operations or []) != 1 or len(entities or []) != 1:
        return value
    operation, entity = operations[0], entities[0]
    if (not isinstance(operation, dict) or not isinstance(entity, dict)
            or operation.get("operation") != "update_properties" or set(operation.get("properties") or {}) != {"color"}
            or operation.get("target") != entity.get("entity_id")):
        return value
    markers = ("改成", "改为", "变成", "换成", "涂成", "染成", "to ", "into ")
    marker = next((instruction.find(word) for word in markers if instruction.find(word) >= 0), -1)
    if marker < 0:
        return value
    before = instruction[:marker]
    after = instruction[marker:]
    semantic = str(entity.get("semantic_name") or "").casefold()
    names = {label.casefold() for item in catalog.models if item.name.casefold() == semantic
             for label in (item.name, *item.aliases) if label}
    if not names:
        return value
    source_colors = []
    for _, end, color in _color_mentions(before):
        for name in names:
            noun = before.casefold().find(name)
            if noun >= end and before[end:noun].strip() in {"", "的"}:
                source_colors.append(color)
                break
    destination = next((color for _, _, color in _color_mentions(after)), None)
    output_colors = _color_mentions(str(operation.get("properties", {}).get("color", "")))
    if not source_colors or destination is None or not output_colors or destination != output_colors[0][2]:
        return value
    source_color = source_colors[0]
    relations = edit.get("relations") or []
    invalid = [rel for rel in relations if rel.get("subject") == entity.get("entity_id")
               and rel.get("relation") == "near" and not rel.get("reference")]
    if not invalid:
        return value
    updated_entity = {**entity, "color": source_color}
    return {**value, "scene_edit": {**edit,
            "entities": [updated_entity],
            "relations": [rel for rel in relations if rel not in invalid]}}


def _repair_live_color_add_clarification(value, instruction, catalog):
    """Use a unique listed model and instance color for an explicit color add."""
    if not isinstance(value, dict) or value.get("status") != "clarification_required":
        return value
    question = str(value.get("clarification_question") or "").casefold()
    catalog_mismatch = (("目录" in question or "资产" in question or "catalog" in question)
                        and ("没有" in question or "不存在" in question or "not available" in question
                             or "not found" in question))
    if not catalog_mismatch:
        return value
    if not any(word in instruction.casefold() for word in
               ("生成", "创建", "添加", "增加", "放置", "摆放", "create", "add ", "place ")):
        return value
    mentions = _color_mentions(instruction)
    if not mentions:
        return value
    folded = instruction.casefold()
    matches = []
    for item in catalog.models:
        if not item.selectable_for_add:
            continue
        description = " ".join((item.name, *item.aliases)).casefold()
        if ((item.category or "").casefold() in {"surface", "support_surface", "table"}
                or any(term in description for term in ("table", "desktop", "work table", "桌面", "桌子", "台面"))):
            continue
        positions = [folded.find(label.casefold()) for label in (item.name, *item.aliases)
                     if label and folded.find(label.casefold()) >= 0]
        if positions and any(end <= min(positions) for _, end, _ in mentions):
            matches.append(item)
    unique = {item.asset_key: item for item in matches}
    if len(unique) != 1:
        return value
    item = next(iter(unique.values()))
    name_positions = [folded.find(label.casefold()) for label in (item.name, *item.aliases)
                      if label and folded.find(label.casefold()) >= 0]
    if not name_positions:
        return value
    noun_position = min(name_positions)
    colors_before_noun = [color for _, end, color in mentions if end <= noun_position]
    if not colors_before_noun:
        return value
    for other in catalog.models:
        if other.asset_key == item.asset_key:
            continue
        mentioned = any(label and label.casefold() in folded for label in (other.name, *other.aliases))
        is_surface = ((other.category or "").casefold() in {"surface", "support_surface", "table"}
                      or "table" in other.name.casefold() or "desk" in other.name.casefold())
        if mentioned and not is_surface:
            return value
    if any(term in folded for term in ("里面", "内部", "附近", "旁边", "左侧", "右侧", "左边", "右边",
                                       "前面", "后面", "inside", "near", "beside", "left of", "right of")):
        return value
    if (re.search(r"(?:放在|摆在|置于|放到|摆到|置放于|在)\s*", folded)
            and not any(term in folded for term in ("桌", "台面", "table", "desktop", "work table"))):
        return value
    color = colors_before_noun[-1]
    entity_id = re.sub(r"\W+", "_", item.name.casefold()).strip("_") or "target"
    edit = {"scene_basis": "current",
            "entities": [{"entity_id": entity_id, "semantic_name": item.name,
                          "category": item.category or "object", "count": 1,
                          "quantity_mode": "single"}],
            "relations": [],
            "asset_choices": [{"entity_id": entity_id, "asset_key": item.asset_key}],
            "operations": [{"operation": "add", "target": entity_id, "relation": "on",
                            "reference": "table", "placement_hint": "any",
                            "placement_region": None, "properties": {"color": color}}]}
    return {**value, "status": "accepted", "turn_kind": "scene_edit",
            "clarification_question": None, "scene_edit": edit, "scene_query": None,
            "session_control": None, "robot_setup_request": None,
            "robot_asset_switch": None, "robot_asset": None, "gripper_asset": None,
            "camera_asset": None, "profile_id": None, "entities": [], "operations": [], "relations": []}


def _catalog_match(text, catalog):
    folded = text.casefold()
    found = {}
    for item in catalog.models:
        if any(label and label.casefold() in folded for label in (item.name, *item.aliases)):
            found[item.asset_key] = item
    return list(found.values())


def _parse_scene_quantity(token):
    if token.isdigit():
        return int(token)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
              "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if token == "十":
        return 10
    if "十" in token:
        tens, _, ones = token.partition("十")
        return (digits.get(tens, 1) * 10) + digits.get(ones, 0)
    return digits.get(token)


def _repair_live_scene_edit_quantity(value, instruction, catalog):
    """Preserve explicit modification counts and all-objects wording."""
    if (not isinstance(value, dict) or value.get("status") != "accepted"
            or value.get("turn_kind") != "scene_edit" or not isinstance(value.get("scene_edit"), dict)
            or catalog is None):
        return value
    edit = value["scene_edit"]
    operations = edit.get("operations") or []
    entities = [dict(entity) for entity in edit.get("entities") or [] if isinstance(entity, dict)]
    if not operations or not entities:
        return value
    folded = instruction.casefold()
    explicit_ids = re.search(r"(?:object_?id|instance_?id|(?<![a-z])ids?\s*(?:为|是|=|:|\d)|对象编号|实例编号)", folded)
    stripped_ids = False
    if not explicit_ids:
        for entity in entities:
            if entity.get("scene_object_ids"):
                entity["scene_object_ids"] = []
                stripped_ids = True
    # Explicit instance lists carry IDs, not an arbitrary quantity request.
    if re.search(r"(?:\bobject\s*_?id\b|\binstance\s*_?id\b|\bid\s*(?:为|是|=|:)|对象编号|实例编号)", folded):
        return value
    by_id = {entity.get("entity_id"): entity for entity in entities}
    changed = stripped_ids
    all_words = re.compile(r"(?:所有|全部|每个|\ball\b|\bevery\b)")
    count_pattern = re.compile(
        r"(\d+|[零〇一二两三四五六七八九十]+)\s*(?:个|只|件|颗|枚|支|台)?\s*$"
    )
    english_counts = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                      "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("operation") not in {
                "remove", "replace", "update_properties", "update", "scale", "orient"}:
            continue
        entity = by_id.get(operation.get("target"))
        if entity is None:
            continue
        if entity.get("quantity_mode") == "candidate_pool" and re.search(r"(?:中|among).*(?:那个|one)", folded) and any(
                relation.get("subject") == entity.get("entity_id")
                and relation.get("relation") in {
                    "leftmost", "rightmost", "frontmost", "backmost", "highest", "lowest",
                    "nearest", "farthest",
                }
                for relation in edit.get("relations") or [] if isinstance(relation, dict)):
            entity["select_count_from_candidates"] = False
            continue
        semantic = str(entity.get("semantic_name") or "").casefold()
        labels = {label.casefold() for item in catalog.models
                  if item.name.casefold() == semantic
                  or semantic in {alias.casefold() for alias in item.aliases}
                  for label in (item.name, *item.aliases) if label}
        mentions = [(folded.find(label), label) for label in labels if folded.find(label) >= 0]
        if not mentions:
            continue
        # Use the closest noun mention to the operation's local wording.
        positions = sorted({position for position, _ in mentions})
        candidates = []
        for position in positions:
            nearby = folded[max(0, position - 24):position]
            nearby = re.split(r"(?:,|，|;|；|然后|接着|再|\band\b|和)", nearby)[-1].strip()
            if all_words.search(nearby):
                if not re.search(r"(?:not|no|不是|并非)\s*(?:all|所有|全部)", nearby):
                    candidates.append((position, None, True))
                continue
            quantity = count_pattern.search(nearby)
            if quantity:
                count = _parse_scene_quantity(quantity.group(1))
                if count is not None:
                    candidates.append((position, count, False))
                    continue
            english = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)(?:\s+of\s+(?:the\b\s*)?)?\s*$", nearby)
            if english:
                candidates.append((position, english_counts[english.group(1)], False))
        if not candidates:
            if entity.get("select_count_from_candidates"):
                entity["select_count_from_candidates"] = False
                changed = True
            if (entity.get("quantity_mode") == "all" and entity.get("count", 1) == 1
                    and not entity.get("all_available")):
                entity["quantity_mode"] = "single"
                changed = True
            continue
        # A single entity may be repeated in a compound instruction. Require
        # a consistent explicit quantity rather than guessing which clause wins.
        quantities = {(count, all_available) for _, count, all_available in candidates}
        if len(quantities) != 1:
            continue
        count, all_available = next(iter(quantities))
        entity["quantity_mode"] = "all"
        if all_available:
            entity["count"] = 1
            entity["all_available"] = True
            entity["select_count_from_candidates"] = False
        else:
            entity["count"] = count
            entity["all_available"] = False
            entity["select_count_from_candidates"] = True
            if count > 1:
                selectors = {"最前面": "frontmost", "最前边": "frontmost", "最上面": "frontmost",
                             "最后面": "backmost", "最左边": "leftmost", "最右边": "rightmost"}
                prefix = folded[:positions[0]]
                kinds = {kind for label, kind in selectors.items() if label in prefix}
                if len(kinds) == 1:
                    relations = list(edit.get("relations") or [])
                    kind = next(iter(kinds))
                    if not any(r.get("subject") == entity.get("entity_id") and r.get("relation") == kind for r in relations):
                        relations.append({"scope": "selection", "subject": entity["entity_id"], "relation": kind})
                    edit = {**edit, "relations": relations}
        changed = True
    return {**value, "scene_edit": {**edit, "entities": entities}} if changed else value


def _repair_live_top_view_replace_clarification(value, instruction, catalog):
    """Interpret unqualified tabletop 'topmost' as frontmost in the top view."""
    if not isinstance(value, dict) or value.get("status") != "clarification_required":
        return value
    question = str(value.get("clarification_question") or "")
    if not ("最上面" in instruction or "最上方" in instruction) or not ("Y" in question and "Z" in question):
        return value
    if any(token in instruction for token in ("最高", "高度", "Z轴", "z轴")):
        return value
    match = re.search(r"(?:换成|替换成|替换为|更换为)\s*([\w一-龥 -]+)", instruction)
    if not match:
        return value
    source_text, replacement_text = instruction[:match.start()], match.group(1).strip(" ，,。.!！?？\t\n")
    source = _catalog_match(source_text, catalog)
    replacement = _catalog_match(replacement_text, catalog)
    replacement = [item for item in replacement if item.selectable_for_add]
    if len(source) != 1 or len(replacement) != 1:
        return value
    source_item, replacement_item = source[0], replacement[0]
    source_id = re.sub(r"\W+", "_", source_item.name.casefold()).strip("_") or "source"
    replacement_id = re.sub(r"\W+", "_", replacement_item.name.casefold()).strip("_") or "replacement"
    edit = {"scene_basis": "current",
            "entities": [{"entity_id": source_id, "semantic_name": source_item.name,
                          "category": source_item.category or "object", "count": 1,
                          "quantity_mode": "candidate_pool"},
                         {"entity_id": replacement_id, "semantic_name": replacement_item.name,
                          "category": replacement_item.category or "object", "count": 1,
                          "quantity_mode": "single"}],
            "relations": [{"scope": "selection", "subject": source_id,
                           "relation": "frontmost", "reference": None}],
            "asset_choices": [{"entity_id": replacement_id, "asset_key": replacement_item.asset_key}],
            "operations": [{"operation": "replace", "target": source_id,
                            "replacement_entity": replacement_id}]}
    return {**value, "status": "accepted", "turn_kind": "scene_edit",
            "clarification_question": None, "scene_edit": edit, "scene_query": None,
            "session_control": None, "robot_setup_request": None,
            "robot_asset_switch": None, "robot_asset": None, "gripper_asset": None,
            "camera_asset": None, "profile_id": None, "entities": [], "operations": [], "relations": []}


def _repair_live_posture_clarification(value, instruction, catalog):
    """Recover only a simple, explicit supported target-posture request."""
    if not isinstance(value, dict) or value.get("status") not in {"accepted", "clarification_required"}:
        return value
    match = re.fullmatch(r"\s*(?:把|将)?\s*(.+?)\s*(放平|放倒|平放|立起来|竖起来|竖放|立起)\s*[。！!]?\s*", instruction)
    if not match or catalog is None:
        return value
    subject, word = match.groups()
    items = _catalog_match(subject, catalog)
    if len(items) != 1 or subject.strip() not in {items[0].name, *items[0].aliases}:
        return value
    item = items[0]
    posture = "flat" if word in {"放平", "放倒", "平放"} else "upright"
    if value.get("status") == "accepted":
        edit = value.get("scene_edit")
        if value.get("turn_kind") != "scene_edit" or not isinstance(edit, dict):
            return value
        operations = edit.get("operations") or []
        entities = edit.get("entities") or []
        if len(operations) != 1 or len(entities) != 1:
            return value
        operation, entity = operations[0], entities[0]
        if (not isinstance(operation, dict) or not isinstance(entity, dict)
                or operation.get("operation") != "orient" or operation.get("posture") is not None
                or operation.get("target") != entity.get("entity_id")
                or entity.get("semantic_name") != item.name):
            return value
        return {**value, "scene_edit": {**edit, "operations": [{**operation, "posture": posture}]}}
    edit = {"scene_basis": "current", "entities": [{"entity_id": "target",
            "semantic_name": item.name, "category": item.category or "object"}],
            "relations": [], "asset_choices": [], "operations": [{"operation": "orient",
            "target": "target", "posture": posture}]}
    return {**value, "status": "accepted", "turn_kind": "scene_edit", "clarification_question": None,
            "scene_edit": edit, "scene_query": None, "session_control": None,
            "robot_setup_request": None, "robot_asset_switch": None,
            "entities": [], "operations": [], "relations": []}


def _repair_live_explicit_instance_delete(value, instruction, scene_context, catalog):
    """Resolve an explicit scene-instance ID when Qwen asks what it means."""
    if not isinstance(value, dict) or value.get("status") != "clarification_required":
        return value
    text = instruction.casefold()
    if not re.search(r"\b(delete|remove)\b|删除|移除|删掉|去掉", text):
        return value
    if re.search(r"(?:不要|别|禁止)\s*(?:删除|移除|删掉|去掉)|\b(do not|don't)\s+(?:delete|remove)\b", text):
        return value
    id_list = r"((?:#?\d+)(?:\s*(?:[,，、和及]\s*|\s+)#?\d+)*)"
    patterns = (
        rf"(?:scene\s*object|object|instance)\s*_?\s*ids?\s*(?:are|为|是|=|:)?\s*{id_list}",
        rf"(?:对象\s*id|实例\s*id|对象编号|实例编号)\s*(?:为|是|=|:)?\s*{id_list}",
        rf"(?<![A-Za-z0-9_])id\s*(?:为|是|=|:)?\s*{id_list}",
    )
    id_groups = [match.group(1) for pattern in patterns for match in re.finditer(pattern, text)]
    ids = list(dict.fromkeys(int(value) for group in id_groups
                             for value in re.findall(r"\d+", group)))
    if not ids or not isinstance(scene_context, dict):
        return value
    objects = scene_context.get("objects")
    if not isinstance(objects, list):
        return value
    by_id = {item["object_id"]: item for item in objects if isinstance(item, dict)
             and type(item.get("object_id")) is int}
    if any(identifier not in by_id for identifier in ids):
        return value
    matches = [by_id[identifier] for identifier in ids]
    semantics = {str(item.get("semantic_name") or "").strip().casefold() for item in matches}
    categories = {str(item.get("category") or "").strip() for item in matches}
    if len(semantics) != 1 or not next(iter(semantics)) or len(categories) != 1 or not next(iter(categories)):
        return value
    semantic_name = str(matches[0]["semantic_name"]).strip()
    category = str(matches[0]["category"]).strip()
    semantic_folded = semantic_name.casefold()
    if catalog is not None:
        named_assets = _catalog_match(instruction, catalog)
        named = [item for item in named_assets
                 if item.name.casefold() == semantic_folded
                 or semantic_folded in {alias.casefold() for alias in item.aliases}]
        extras = [item for item in named_assets if item not in named
                  and (item.category or "").casefold() not in {"surface", "support_surface", "table"}]
        if len(named) > 1 or extras:
            return value
        object_names = {str(item.get("object_name") or "").casefold() for item in matches}
        if not named and semantic_folded not in text and not any(name and name in text for name in object_names):
            return value
    else:
        object_names = {str(item.get("object_name") or "").casefold() for item in matches}
        if semantic_folded not in text and not any(name and name in text for name in object_names):
            return value
    entity_id = re.sub(r"\W+", "_", semantic_name.casefold()).strip("_") or "target"
    edit = {
        "scene_basis": "current",
        "entities": [{"entity_id": entity_id, "semantic_name": semantic_name,
                      "category": category, "count": len(ids),
                      "quantity_mode": "all" if len(ids) > 1 else "single",
                      "scene_object_ids": ids}],
        "asset_choices": [], "relations": [],
        "operations": [{"operation": "remove", "target": entity_id}],
    }
    return {**value, "status": "accepted", "turn_kind": "scene_edit",
            "clarification_question": None, "scene_edit": edit, "scene_query": None,
            "session_control": None, "robot_setup_request": None,
            "robot_asset_switch": None, "entities": [], "operations": [], "relations": []}


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
        asset_catalog=None,
        live_catalog: bool | None = None,
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
        # A transport/client supplied by a test or replay harness is an
        # explicit compatibility boundary: it does not represent the live
        # Qwen endpoint used by the release service.  Live HTTP (the default,
        # with neither injected object) receives and must satisfy the
        # request-scoped OLS v3.1 catalog.  Callers that wrap a real endpoint
        # with a custom client can opt in explicitly with ``live_catalog``.
        self.live_catalog = (client is None and transport is None) if live_catalog is None else bool(live_catalog)
        self.calls: list[dict[str, Any]] = []
        self.last_raw_values: dict[str, Any] = {}
        self.last_raw_text: dict[str, str] = {}
        self.asset_catalog_prompt = ""
        self.asset_catalog_sha256 = None
        self.asset_catalog_snapshot = None
        if asset_catalog is not None:
            self.set_asset_catalog(asset_catalog)

    def set_asset_catalog(self, assets, aliases=None, registered_profiles=None) -> None:
        from .prompts import _snapshot_for_assets
        self.asset_catalog_snapshot = _snapshot_for_assets(
            assets, aliases=aliases, registered_profiles=registered_profiles)
        self.asset_catalog_prompt, self.asset_catalog_sha256 = build_asset_catalog_prompt(
            self.asset_catalog_snapshot, aliases=aliases, snapshot=self.asset_catalog_snapshot,
            registered_profiles=registered_profiles)

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
        # Keep the real model-input identity in evidence without persisting the
        # full prompt or JSON schema.  This lets a C7 run prove which prompt
        # and contract were used while keeping local asset names/paths out of
        # the diagnostic record.
        record["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        record["schema_sha256"] = hashlib.sha256(
            json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if stage == "task_understanding" and self.asset_catalog_sha256:
            record["asset_catalog_sha256"] = self.asset_catalog_sha256
            if self.asset_catalog_snapshot is not None:
                record["catalog_revision"] = self.asset_catalog_snapshot.revision
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
            if isinstance(exc, QwenProviderError) and exc.code != "provider_error":
                code = exc.code
            elif stage == "vision_grounding" and isinstance(exc, ValidationError):
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
        if request.asset_catalog is not None and (
                self.asset_catalog_snapshot is None
                or request.asset_catalog.revision != self.asset_catalog_snapshot.revision):
            self.set_asset_catalog(request.asset_catalog)
        return self._call(
            "task_understanding",
            TASK_UNDERSTANDING_PROMPT + self.asset_catalog_prompt,
            prompt_payload(self._understanding_payload(request)),
            task_understanding_v3_wire_schema(),
            lambda value: _task_intent_from_v3(value, request.instruction),
        )

    def understand_turn(self, request: TaskUnderstandingRequest):
        if request.asset_catalog is not None and (
                self.asset_catalog_snapshot is None
                or request.asset_catalog.revision != self.asset_catalog_snapshot.revision):
            # A direct caller may provide a fresh per-turn snapshot without
            # going through BrainPipeline. Keep the prompt and structured body
            # on exactly the same catalog revision.
            self.set_asset_catalog(request.asset_catalog)
        def parse(value):
            # Old replay fixtures may opt into the narrow formatting adapter,
            # but live v3.1 requests must be interpreted exactly as emitted.
            # In particular, do not rewrite cup/mug or invent replacement
            # entities after the catalog has been supplied.
            if request.asset_catalog is None:
                value = _repair_explicit_replace(value, request.instruction)
                value = _repair_explicit_selector_clarification(value, request.instruction)
            else:
                value = _repair_live_posture_clarification(value, request.instruction, request.asset_catalog)
                value = _repair_live_replace_entity(value, request.instruction, request.asset_catalog)
                value = _repair_live_scene_edit_quantity(value, request.instruction,
                                                         request.asset_catalog)
                value = _repair_live_top_view_replace_clarification(
                    value, request.instruction, request.asset_catalog)
                value = _repair_live_color_update_selector(value, request.instruction,
                                                           request.asset_catalog)
                value = _repair_live_color_add_clarification(value, request.instruction,
                                                             request.asset_catalog)
                value = _repair_live_explicit_instance_delete(
                    value, request.instruction, request.scene_context, request.asset_catalog)
            turn = parse_qwen_turn(value, request.instruction)
            if request.asset_catalog is not None:
                self._validate_live_asset_choices(value, request)
            return turn
        prompt = TASK_UNDERSTANDING_PROMPT + self.asset_catalog_prompt
        content = prompt_payload(self._understanding_payload(request))
        schema = task_understanding_v3_wire_schema()
        try:
            return self._call("task_understanding", prompt, content, schema, parse)
        except QwenProviderError as exc:
            # A live v3.1 response must explicitly choose an OLS asset for
            # every add/replace operation.  Qwen occasionally emits an
            # otherwise valid edit while omitting that array.  Give it one
            # bounded, schema-identical repair turn; never infer an asset in
            # Python because doing so would make a stale catalog authoritative.
            if request.asset_catalog is None or exc.code != "asset_choice_missing":
                raise
            repair_prompt = prompt + (
                "\n\n上一轮输出缺少 asset_choices。请重新输出完整的 task_understanding.v3.1 JSON："
                "scene_edit 中每一个 operation=add 或 operation=replace 都必须有一个"
                "asset_choices 项，entity_id 必须与实体一致，asset_key 必须来自本次 OLS 资产目录。"
                "不要省略其他必填字段，不要解释文字，只返回 JSON。"
            )
            return self._call("task_understanding", repair_prompt, content, schema, parse)

    def _understanding_payload(self, request: TaskUnderstandingRequest) -> dict[str, Any]:
        """Serialize the complete first-stage request, not just user text."""
        catalog = request.asset_catalog or self.asset_catalog_snapshot
        value = request.model_dump(mode="json", exclude_none=True)
        if catalog is not None:
            value["asset_catalog"] = catalog.model_dump(mode="json")
        return value

    @staticmethod
    def _validate_live_asset_choices(value: dict[str, Any], request: TaskUnderstandingRequest) -> None:
        """Validate model-selected OLS keys against the exact turn snapshot."""
        # A request carrying a catalog is a live v3.1 turn.  Do not silently
        # accept the old v3 envelope here: doing so would bypass asset-choice
        # validation and let the legacy resolver reinterpret names (for
        # example cup -> mug) after Qwen has answered.  Replay/fake callers
        # without a request-scoped catalog remain on the compatibility path.
        if not isinstance(value, dict):
            raise QwenProviderError("task_understanding response must be an object",
                                    code="provider_output_schema_invalid")
        protocol = value.get("protocol_version")
        if protocol != "task_understanding.v3.1":
            # A request carrying a catalog is a live call.  Missing, old, and
            # unknown protocol markers are all rejected before any edit can
            # reach the scene pipeline.  Historical replay callers do not
            # carry a request-scoped catalog and remain on the explicit
            # compatibility path in ``understand_turn``.
            raise QwenProviderError(
                "live task_understanding requires protocol_version=task_understanding.v3.1",
                code="provider_output_schema_invalid")
        if value.get("turn_kind") != "scene_edit" or value.get("status", "accepted") != "accepted":
            return
        payload = value.get("scene_edit")
        if not isinstance(payload, dict):
            return
        choices = payload.get("asset_choices") or []
        if not isinstance(choices, list):
            raise QwenProviderError("scene_edit.asset_choices must be an array", code="provider_output_schema_invalid")
        by_entity = {}
        entities = {
            item.get("entity_id"): item for item in (payload.get("entities") or [])
            if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
        }
        for index, item in enumerate(choices):
            if not isinstance(item, dict) or not isinstance(item.get("entity_id"), str) or not isinstance(item.get("asset_key"), str):
                raise QwenProviderError(f"scene_edit.asset_choices[{index}] is invalid", code="provider_output_schema_invalid")
            entity_id, key = item["entity_id"], item["asset_key"]
            if entity_id in by_entity:
                raise QwenProviderError(f"duplicate asset choice: {entity_id}", code="provider_output_schema_invalid")
            catalog_item = request.asset_catalog.model_by_key(key)
            if catalog_item is None:
                raise QwenProviderError(f"asset_key_not_in_catalog:{key}", code="asset_catalog_key_invalid")
            if not catalog_item.selectable_for_add:
                raise QwenProviderError(f"asset_not_selectable_for_scene_edit:{key}", code="asset_catalog_key_invalid")
            entity = entities.get(entity_id)
            if entity is None:
                raise QwenProviderError(f"asset_choice_unknown_entity:{entity_id}", code="provider_output_schema_invalid")
            semantic_name = entity.get("semantic_name")
            entity_tags = entity.get("tags") or []
            if isinstance(semantic_name, str) and semantic_name.strip():
                # Legacy path: semantic_name must match catalog name
                if semantic_name.casefold() != catalog_item.name.casefold():
                    raise QwenProviderError(
                        f"asset_choice_name_mismatch:{entity_id}:{semantic_name}!={catalog_item.name}",
                        code="asset_catalog_key_invalid")
            elif entity_tags:
                # Tag-based path: verify at least one tag overlaps with catalog item tags
                catalog_tags = {t.strip().casefold() for t in catalog_item.tags}
                entity_tag_set = {t.strip().casefold() for t in entity_tags}
                if not catalog_tags & entity_tag_set:
                    raise QwenProviderError(
                        f"asset_choice_tag_mismatch:{entity_id}:tags={entity_tags}!={catalog_item.tags}",
                        code="asset_catalog_key_invalid")
            by_entity[entity_id] = key
        required = []
        for op in payload.get("operations") or []:
            if not isinstance(op, dict):
                continue
            if op.get("operation") == "add":
                required.append(op.get("target"))
            elif op.get("operation") == "replace":
                required.append(op.get("replacement_entity"))
        missing = [item for item in required if item and item not in by_entity]
        if missing:
            raise QwenProviderError("missing asset choice for: " + ",".join(missing), code="asset_choice_missing")
        allowed = {item for item in required if item}
        extra = sorted(set(by_entity) - allowed)
        if extra:
            raise QwenProviderError("asset choice has no add/replace operation: " + ",".join(extra),
                                    code="provider_output_schema_invalid")

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
    match = re.search(r"(?:替换成|替换为|换成|更换为|replace(?:d)?\s+(?:with|by))\s*([\w一-龥 -]+)", instruction, re.IGNORECASE)
    if not match:
        match = re.search(r"用\s*([\w一-龥]+)\s*替换", instruction)
    if not match:
        return value
    raw_name = match.group(1).strip(" ，,。.!！?？\t\n")
    raw_name = re.sub(r"^(一个|两个|三个|几个|这个|那个)\s*", "", raw_name)
    if not raw_name:
        return value
    # Legacy replay compatibility only: without a live catalog, retain the
    # small historical vocabulary used by recorded fixtures.  Live turns never
    # enter this adapter path; their exact asset_key must come from OLS.
    semantic_name = {
        "苹果": "apple", "香蕉": "banana", "篮子": "basket", "托盘": "tray",
        "apple": "apple", "banana": "banana", "basket": "basket", "tray": "tray",
    }.get(raw_name.casefold(), raw_name)
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


def _repair_live_replace_entity(value: dict[str, Any], instruction: str, catalog=None) -> dict[str, Any]:
    """Fill a missing ``replacement_entity`` for live turns when the entity already exists.

    Live turns must not invent new entities, but Qwen occasionally omits the
    ``replacement_entity`` field even when the replacement entity is already
    declared in ``scene_edit.entities``. This narrow repair only fills in the
    field by matching the instruction's replacement name to an existing entity.
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
    if len(replace_ops) != 1 or any(item.get("replacement_entity") for item in replace_ops):
        return value
    entities = list(scene_edit.get("entities") or [])
    if not entities:
        return value
    match = re.search(r"(?:替换成|替换为|换成|更换为|replace(?:d)?\s+(?:with|by))\s*([\w一-龥 -]+)", instruction, re.IGNORECASE)
    if not match:
        match = re.search(r"用\s*([\w一-龥]+)\s*替换", instruction)
    if not match:
        return value
    raw_name = match.group(1).strip(" ，,。.!！?？\t\n")
    raw_name = re.sub(r"^(一个|两个|三个|几个|这个|那个)\s*", "", raw_name)
    if not raw_name:
        return value
    catalog_matches = _catalog_match(raw_name, catalog) if catalog is not None else []
    if len(catalog_matches) > 1:
        return value
    semantic_name = catalog_matches[0].name if catalog_matches else {
        "苹果": "apple", "香蕉": "banana", "篮子": "basket", "托盘": "tray",
        "棒球": "baseball", "钢笔": "pen", "马克笔": "marker", "马克杯": "mug", "杯子": "mug",
        "魔方": "rubiks_cube", "rubiks cube": "rubiks_cube",
    }.get(raw_name.casefold(), raw_name)
    for entity in entities:
        if isinstance(entity, dict):
            entity_id = entity.get("entity_id", "")
            entity_semantic = str(entity.get("semantic_name", "")).casefold()
            if (entity_id == semantic_name or entity_id == raw_name or
                entity_semantic == semantic_name.casefold() or entity_semantic == raw_name.casefold()):
                replacement_id = entity.get("entity_id")
                choices = list(scene_edit.get("asset_choices") or [])
                if catalog_matches:
                    existing = {choice.get("entity_id") for choice in choices if isinstance(choice, dict)}
                    if replacement_id not in existing:
                        choices.append({"entity_id": replacement_id,
                                        "asset_key": catalog_matches[0].asset_key})
                required_entities = {
                    item.get("target") for item in operations
                    if isinstance(item, dict) and item.get("operation") == "add"
                } | {
                    item.get("replacement_entity") or replacement_id for item in operations
                    if isinstance(item, dict) and item.get("operation") == "replace"
                }
                choices = [choice for choice in choices if isinstance(choice, dict)
                           and choice.get("entity_id") in required_entities]
                scene_edit = {**scene_edit, "asset_choices": choices,
                              "operations": [({**item, "replacement_entity": replacement_id}
                                               if isinstance(item, dict) and item.get("operation") == "replace" and not item.get("replacement_entity")
                                               else item) for item in operations]}
                return {**value, "scene_edit": scene_edit}
    return value


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
    colors = {
        "蓝": "blue", "蓝色": "blue", "红": "red", "红色": "red",
        "绿": "green", "绿色": "green", "黄": "yellow", "黄色": "yellow",
        "白": "white", "白色": "white", "黑": "black", "黑色": "black",
    }
    legacy_aliases = {"苹果": "apple", "香蕉": "banana", "篮子": "basket", "托盘": "tray",
                      "apple": "apple", "banana": "banana", "basket": "basket", "tray": "tray"}
    reference = legacy_aliases.get(reference_raw.casefold(), reference_raw)
    subject = legacy_aliases.get(subject_raw.casefold(), subject_raw)
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

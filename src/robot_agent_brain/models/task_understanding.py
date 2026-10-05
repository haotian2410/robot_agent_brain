from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.turn import BrainTurn, SceneEditPlan, SceneEditIntent, SceneQueryIntent, SessionControlIntent, TurnKind, TurnStatus

from ..contracts.spatial import RelationScope, SpatialRelation, SpatialRelationType
from ..contracts.task_intent import Direction, MotionScale, Operation, PlacementTarget, QuantityMode, TaskEntity, TaskIntent, TaskType


class TaskUnderstandingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1)


class TaskUnderstandingProvider(Protocol):
    def understand(self, request: TaskUnderstandingRequest) -> TaskIntent: ...


class ParseEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    category: str
    color: str | None = None
    count: int = Field(default=1, ge=1)
    quantity_mode: QuantityMode = QuantityMode.SINGLE
    aliases: list[str] = Field(default_factory=list)
    dialogue_ref: bool = False
    dialogue_ref_set: bool = False
    all_available: bool = False
    category_only: bool = False
    exclude_scene_object_ids: list[str] = Field(default_factory=list)


class ParseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TaskType
    source: str | None = None
    destination: str | None = None
    target: str | None = None
    reference: str | None = None
    motion_direction: Direction | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2)
    motion_scale: MotionScale | None = None
    placement_target: PlacementTarget | None = None
    depends_on: list[str] = Field(default_factory=list)
    assignment_mode: str = Field(default="broadcast", pattern=r"^(broadcast|pairwise|repeat_all|relation_matched)$")


class ParseRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: RelationScope = RelationScope.SELECTION
    subject: str
    relation: SpatialRelationType
    reference: str | None = None


class TaskParseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TurnStatus = TurnStatus.ACCEPTED
    turn_kind: TurnKind = TurnKind.ROBOT_TASK
    scene_edit: SceneEditPlan | SceneEditIntent | None = None
    scene_query: SceneQueryIntent | None = None
    session_control: SessionControlIntent | None = None
    entities: list[ParseEntity] = Field(default_factory=list)
    operations: list[ParseOperation] = Field(default_factory=list)
    relations: list[ParseRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_turn(self):
        payloads = {TurnKind.SCENE_EDIT: self.scene_edit, TurnKind.SCENE_QUERY: self.scene_query, TurnKind.SESSION_CONTROL: self.session_control}
        if self.status != TurnStatus.ACCEPTED:
            if self.entities or self.operations or self.relations or any(v is not None for v in payloads.values()):
                raise ValueError("task_semantic_invalid: rejected turn has payload")
            return self
        if self.turn_kind == TurnKind.ROBOT_TASK:
            if not self.entities or not self.operations or any(v is not None for v in payloads.values()):
                raise ValueError("task_semantic_invalid: robot task needs only entities and operations")
        elif self.turn_kind in payloads:
            if self.entities or self.operations or self.relations or payloads[self.turn_kind] is None or sum(v is not None for v in payloads.values()) != 1:
                raise ValueError("task_semantic_invalid: turn payload mismatch")
        else:
            raise ValueError("task_semantic_invalid: unsupported turn cannot be accepted")
        ids = {e.id for e in self.entities}
        if any(r.subject not in ids or (r.reference and r.reference not in ids) for r in self.relations):
            raise ValueError("task_semantic_invalid: relation references unknown entities")
        return self

    def to_task_intent(self, instruction: str) -> TaskIntent:
        if self.status != TurnStatus.ACCEPTED or self.turn_kind != TurnKind.ROBOT_TASK:
            raise ValueError("task_semantic_invalid: no robot task payload")
        moves = [o for o in self.operations if o.type == TaskType.MOVE]
        spans = _extract_motion_spans(instruction)
        if moves and spans and len(moves) != len(spans):
            raise ValueError("motion_clause_binding_ambiguous")
        operation_values = []
        span_index = 0
        for item in self.operations:
            values = item.model_dump(exclude={"type"})
            entity_counts = {entity.id: entity.count for entity in self.entities}
            pairwise_clause = ("分别" in instruction or "一一对应" in instruction)
            role_counts = [entity_counts.get(role, 1) for role in (item.source, item.target, item.destination, item.reference) if role]
            if values.get("assignment_mode") == "broadcast" and pairwise_clause and sum(count > 1 for count in role_counts) >= 2:
                values["assignment_mode"] = "pairwise"
            if item.type == TaskType.MOVE and spans:
                span = spans[span_index]
                span_index += 1
                values.update(motion_direction=span.direction, distance_m=span.distance_m, motion_scale=span.motion_scale)
            operation_values.append(Operation(operation_id=f"op-{len(operation_values)+1}", task_type=item.type, **values))
        entity_ids = {item.id for item in self.entities}
        relations = [SpatialRelation(
            scope=item.scope, subject=item.subject, relation=item.relation, reference=item.reference,
        ) for item in self.relations]
        if any(item.subject not in entity_ids or (item.reference and item.reference not in entity_ids) for item in relations):
            raise ValueError("task_semantic_invalid: relation references unknown entities")
        return TaskIntent(
            instruction=instruction,
            entities=[TaskEntity(
                entity_id=item.id,
                semantic_name=item.name,
                category=item.category,
                color=item.color,
                count=item.count,
                quantity_mode=item.quantity_mode,
                aliases=item.aliases, dialogue_ref=item.dialogue_ref, dialogue_ref_set=item.dialogue_ref_set, all_available=item.all_available,
                category_only=item.category_only,
                exclude_scene_object_ids=item.exclude_scene_object_ids,
            ) for item in self.entities],
            operations=operation_values,
            spatial_relations=relations,
        )

    def to_brain_turn(self, instruction: str) -> BrainTurn:
        task = self.to_task_intent(instruction) if self.status == TurnStatus.ACCEPTED and self.turn_kind == TurnKind.ROBOT_TASK else None
        status = self.status
        return BrainTurn(status=status, turn_kind=self.turn_kind, instruction=instruction, task_intent=task, scene_edit=self.scene_edit, scene_query=self.scene_query, session_control=self.session_control)


_DIRECTION_PATTERNS = (
    (r"(?:向|往|朝)\s*左\s*(?:移(?:动)?|挪)|左移", Direction.LEFT),
    (r"(?:向|往|朝)\s*右\s*(?:移(?:动)?|挪)|右移", Direction.RIGHT),
    (r"(?:向|往|朝)\s*前\s*(?:移(?:动)?|挪)|前移", Direction.FRONT),
    (r"(?:向|往|朝)\s*后\s*(?:移(?:动)?|挪)|后移", Direction.BACK),
    (r"(?:向|往|朝)\s*上\s*(?:移(?:动)?|挪)|上移", Direction.UP),
    (r"(?:向|往|朝)\s*下\s*(?:移(?:动)?|挪)|下移", Direction.DOWN),
)
_DISTANCE = re.compile(r"(半|\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+(?:点[零一二两三四五六七八九]+)?)\s*(毫米|mm|厘米|cm|米|m)", re.IGNORECASE)

def _number(text):
    if text == "半":
        return 0.5
    if "点" in text:
        left, right = text.split("点", 1)
        return _number(left) + sum((int(dict(zip("零一二两三四五六七八九", "01223456789"))[c]) * 10 ** -(i + 1)) for i, c in enumerate(right))
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    digits = dict(zip("零一二两三四五六七八九", [0,1,2,2,3,4,5,6,7,8,9]))
    if "百" in text:
        left, right = text.split("百", 1)
        return (digits[left] if left else 1) * 100 + (_number(right) if right else 0)
    if "十" in text:
        left, right = text.split("十", 1)
        return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    return digits[text]

@dataclass(frozen=True)
class ExplicitMotionSpan:
    direction: Direction
    distance_m: float | None
    motion_scale: MotionScale | None
    start: int
    end: int

def _extract_motion_spans(instruction: str) -> list[ExplicitMotionSpan]:
    matches = []
    for pattern, direction in _DIRECTION_PATTERNS:
        for match in re.finditer(pattern, instruction):
            if not any(match.start() < end and match.end() > start for start, end, _ in matches):
                matches.append((match.start(), match.end(), direction))
    matches.sort(key=lambda item: item[0])
    spans = []
    for index, (start, end, direction) in enumerate(matches):
        window_end = matches[index + 1][0] if index + 1 < len(matches) else len(instruction)
        separator = re.search(r"[，,。；;]|然后|再把", instruction[end:window_end])
        if separator:
            window_end = end + separator.start()
        distance_match = _DISTANCE.search(instruction, end, window_end)
        distance = None
        if distance_match:
            distance = _number(distance_match.group(1))
            if distance_match.group(2).casefold() in {"毫米", "mm"}:
                distance /= 1000.0
            elif distance_match.group(2).casefold() in {"厘米", "cm"}:
                distance /= 100.0
        phrase = instruction[max(0, start - 4):window_end]
        scale = None
        if distance is None and any(token in phrase for token in ("大幅", "很多", "很远")):
            scale = MotionScale.LARGE
        elif distance is None and any(token in phrase for token in ("一些", "一段", "适中", "远一些")):
            scale = MotionScale.MEDIUM
        elif distance is None and any(token in phrase for token in ("一点", "稍微", "轻微", "远一点")):
            scale = MotionScale.SMALL
        spans.append(ExplicitMotionSpan(direction, distance, scale, start, distance_match.end() if distance_match else end))
    return spans


def normalize_motion_language(intent: TaskIntent) -> TaskIntent:
    """Make the user's explicit distance authoritative over model scale output."""
    operations = []
    move_count = sum(operation.task_type.value == "move" for operation in intent.operations)
    spans = _extract_motion_spans(intent.instruction)
    if move_count and spans and len(spans) != move_count:
        raise ValueError("motion_clause_binding_ambiguous: move operations and motion clauses differ")
    if not spans:
        return intent
    span_index = 0
    for operation in intent.operations:
        if operation.task_type.value != "move":
            operations.append(operation)
            continue
        span = spans[span_index]
        span_index += 1
        if span.distance_m is None and span.motion_scale is None and operation.distance_m is None and operation.motion_scale is None:
            raise ValueError("motion_distance_evidence_missing")
        values = operation.model_dump()
        values["motion_direction"] = span.direction
        if span.distance_m is not None or span.motion_scale is not None:
            values.update(distance_m=span.distance_m, motion_scale=span.motion_scale)
        operations.append(Operation.model_validate(values))
    return intent.model_copy(update={"operations": operations})

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.turn import BrainTurn, SceneEditIntent, SceneQueryIntent, SessionControlIntent, TurnKind, TurnStatus

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
    scene_edit: SceneEditIntent | None = None
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
            ) for item in self.entities],
            operations=[Operation(
                operation_id=f"op-{index}",
                task_type=item.type,
                source=item.source,
                destination=item.destination,
                target=item.target,
                reference=item.reference,
                motion_direction=item.motion_direction,
                distance_m=item.distance_m,
                motion_scale=item.motion_scale,
                placement_target=item.placement_target,
                depends_on=item.depends_on,
            ) for index, item in enumerate(self.operations, start=1)],
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
_DISTANCE = re.compile(r"(\d+(?:\.\d+)?)\s*(厘米|cm|米|m)", re.IGNORECASE)

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
        distance_match = _DISTANCE.search(instruction, end, window_end)
        distance = None
        if distance_match:
            distance = float(distance_match.group(1))
            if distance_match.group(2).casefold() in {"厘米", "cm"}:
                distance /= 100.0
        phrase = instruction[end:window_end]
        scale = None if distance is not None else MotionScale.SMALL
        if distance is None and any(token in phrase for token in ("大幅", "很多", "很远")):
            scale = MotionScale.LARGE
        elif distance is None and any(token in phrase for token in ("一些", "一段", "适中", "远一些")):
            scale = MotionScale.MEDIUM
        spans.append(ExplicitMotionSpan(direction, distance, scale, start, distance_match.end() if distance_match else end))
    return spans


def normalize_motion_language(intent: TaskIntent) -> TaskIntent:
    """Make the user's explicit distance authoritative over model scale output."""
    operations = []
    move_count = sum(operation.task_type.value == "move" for operation in intent.operations)
    spans = _extract_motion_spans(intent.instruction)
    if move_count and len(spans) != move_count:
        raise ValueError("motion_clause_binding_ambiguous: move operations and motion clauses differ")
    span_index = 0
    for operation in intent.operations:
        if operation.task_type.value != "move":
            operations.append(operation)
            continue
        span = spans[span_index]
        span_index += 1
        operations.append(operation.model_copy(update={"motion_direction": span.direction, "distance_m": span.distance_m, "motion_scale": span.motion_scale}))
    return intent.model_copy(update={"operations": operations})

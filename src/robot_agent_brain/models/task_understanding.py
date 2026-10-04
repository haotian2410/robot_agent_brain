from __future__ import annotations

import re
from typing import Protocol
from pydantic import BaseModel, ConfigDict, Field

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


class TaskParseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = "accepted"
    entities: list[ParseEntity]
    operations: list[ParseOperation]

    def to_task_intent(self, instruction: str) -> TaskIntent:
        return TaskIntent(
            instruction=instruction,
            entities=[TaskEntity(
                entity_id=item.id,
                semantic_name=item.name,
                category=item.category,
                color=item.color,
                count=item.count,
                quantity_mode=item.quantity_mode,
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
            ) for index, item in enumerate(self.operations, start=1)],
        )


_DIRECTION_PATTERNS = (
    (r"(?:向|往|朝)\s*左\s*(?:移(?:动)?|挪)|左移", Direction.LEFT),
    (r"(?:向|往|朝)\s*右\s*(?:移(?:动)?|挪)|右移", Direction.RIGHT),
    (r"(?:向|往|朝)\s*前\s*(?:移(?:动)?|挪)|前移", Direction.FRONT),
    (r"(?:向|往|朝)\s*后\s*(?:移(?:动)?|挪)|后移", Direction.BACK),
    (r"(?:向|往|朝)\s*上\s*(?:移(?:动)?|挪)|上移", Direction.UP),
    (r"(?:向|往|朝)\s*下\s*(?:移(?:动)?|挪)|下移", Direction.DOWN),
)
_DISTANCE = re.compile(r"(\d+(?:\.\d+)?)\s*(厘米|cm|米|m)", re.IGNORECASE)


def normalize_motion_language(intent: TaskIntent) -> TaskIntent:
    """Make the user's explicit distance authoritative over model scale output."""
    operations = []
    for operation in intent.operations:
        if operation.task_type.value != "move":
            operations.append(operation)
            continue
        direction = operation.motion_direction
        for pattern, candidate in _DIRECTION_PATTERNS:
            if re.search(pattern, intent.instruction):
                direction = candidate
                break
        distance_match = _DISTANCE.search(intent.instruction)
        if distance_match:
            distance = float(distance_match.group(1))
            if distance_match.group(2).casefold() in {"厘米", "cm"}:
                distance /= 100.0
            operations.append(operation.model_copy(update={
                "motion_direction": direction,
                "distance_m": distance,
                "motion_scale": None,
            }))
            continue
        scale = operation.motion_scale
        if any(token in intent.instruction for token in ("大幅", "很多", "很远")):
            scale = MotionScale.LARGE
        elif any(token in intent.instruction for token in ("一些", "一段", "适中", "远一些")):
            scale = MotionScale.MEDIUM
        elif any(token in intent.instruction for token in ("一点", "稍微", "轻微", "远一点")):
            scale = MotionScale.SMALL
        operations.append(operation.model_copy(update={"motion_direction": direction, "motion_scale": scale}))
    return intent.model_copy(update={"operations": operations})

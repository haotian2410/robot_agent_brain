from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .spatial import SpatialRelation
from .scene import SceneId


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskType(StrEnum):
    LOCATE = "locate"
    SEARCH = "search"
    MOVE = "move"
    GRASP = "grasp"
    RELEASE = "release"
    PICK_AND_PLACE = "pick_and_place"
    PRESS = "press"
    OPEN = "open"
    CLOSE = "close"


class Direction(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    FRONT = "front"
    BACK = "back"
    UP = "up"
    DOWN = "down"


class MotionScale(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class QuantityMode(StrEnum):
    SINGLE = "single"
    CANDIDATE_POOL = "candidate_pool"
    ALL = "all"


class PlacementTarget(StrictModel):
    kind: str = Field(pattern=r"^(container_interior|support_surface|relative_object|free_space)$")
    reference: str | None = None
    relation: str | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.kind == "relative_object" and (not self.reference or not self.relation):
            raise ValueError("relative_object placement requires reference and relation")
        if self.kind == "container_interior" and self.relation not in {None, "inside"}:
            raise ValueError("container placement relation must be inside")
        if self.kind == "free_space" and self.relation is not None:
            raise ValueError("free_space placement allows an optional support reference, not a relation")
        return self


class TaskEntity(StrictModel):
    entity_id: str = Field(pattern=r"^[\w-]+$")
    semantic_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    color: str | None = None
    aliases: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1)
    quantity_mode: QuantityMode = QuantityMode.SINGLE
    dialogue_ref: bool = False
    dialogue_ref_set: bool = False
    all_available: bool = False
    category_only: bool = False
    exclude_scene_object_ids: list[SceneId] = Field(default_factory=list)


class Operation(StrictModel):
    operation_id: str = Field(pattern=r"^op-[\w-]+$")
    task_type: TaskType
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

    @model_validator(mode="after")
    def validate_operation(self):
        from ..semantics.operation_contracts import validate_operation_contract
        validate_operation_contract(self)
        return self


class TaskIntent(StrictModel):
    instruction: str = Field(min_length=1)
    entities: list[TaskEntity]
    operations: list[Operation]
    spatial_relations: list[SpatialRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        entity_ids = {item.entity_id for item in self.entities}
        if len(entity_ids) != len(self.entities):
            raise ValueError("task_semantic_invalid: entity_id must be unique")
        operation_ids = {item.operation_id for item in self.operations}
        if len(operation_ids) != len(self.operations):
            raise ValueError("task_semantic_invalid: operation ids must be unique")
        previous = set()
        for operation in self.operations:
            refs = {value for value in (operation.source, operation.destination, operation.target, operation.reference) if value}
            if not refs <= entity_ids:
                raise ValueError(f"task_semantic_invalid: operation references unknown entities: {sorted(refs - entity_ids)}")
            if not set(operation.depends_on) <= previous:
                raise ValueError("task_semantic_invalid: invalid operation depends_on")
            previous.add(operation.operation_id)
            if operation.placement_target and operation.placement_target.reference and operation.placement_target.reference not in entity_ids:
                raise ValueError("task_semantic_invalid: unknown placement reference")
        for relation in self.spatial_relations:
            if relation.subject not in entity_ids or (relation.reference and relation.reference not in entity_ids):
                raise ValueError("task_semantic_invalid: spatial relation references unknown entities")
        return self

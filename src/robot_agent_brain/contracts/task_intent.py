from __future__ import annotations

from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .spatial import (PLACEMENT_TARGET_KINDS, SpatialRelation, TabletopRegion)
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
    kind: str = Field(pattern=r"^(" + "|".join(PLACEMENT_TARGET_KINDS) + r")$")
    reference: str | None = None
    relation: str | None = None
    # A robot placement records the requested tabletop region; unlike the
    # editor it does not compute or guarantee a collision-free landing point.
    region: TabletopRegion | None = None

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
    semantic_name: str = Field(default="")
    category: str = Field(min_length=1)
    color: str | None = None
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1)
    quantity_mode: QuantityMode = QuantityMode.SINGLE
    dialogue_ref: bool = False
    dialogue_ref_set: bool = False
    all_available: bool = False
    select_count_from_candidates: bool = False
    scene_object_ids: list[SceneId] = Field(default_factory=list)
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
    arm: Literal["left", "right", "single"] | None = None
    assignment_mode: str = Field(default="broadcast", pattern=r"^(broadcast|pairwise|repeat_all|relation_matched)$")

    @model_validator(mode="after")
    def validate_operation(self):
        from ..semantics.operation_contracts import validate_operation_contract
        validate_operation_contract(self)
        return self


class TaskIntent(StrictModel):
    @property
    def requires_dual(self):
        return self.arm_usage == "both_required" or {op.arm for op in self.operations} >= {"left", "right"}

    instruction: str = Field(min_length=1)
    arm_usage: Literal["unspecified", "both_required"] = "unspecified"
    entities: list[TaskEntity]
    operations: list[Operation]
    spatial_relations: list[SpatialRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        if (len(self.operations) == 2 and "完成后再" in self.instruction
                and self.operations[0].operation_id not in self.operations[1].depends_on):
            raise ValueError("task_explicit_dependency_missing")
        entity_ids = {item.entity_id for item in self.entities}
        # A reference may be a declared task entity or a registered
        # environment reference (for example ``table``/``桌面``).  The latter
        # is resolved against the concrete scene by the grounding layer; it is
        # never silently converted into a synthetic TaskEntity.
        from ..semantics.scene_references import SceneReferenceCatalog
        catalog = SceneReferenceCatalog()
        def known_reference(value):
            return value in entity_ids or catalog.lookup(value) is not None
        if len(entity_ids) != len(self.entities):
            raise ValueError("task_semantic_invalid: entity_id must be unique")
        operation_ids = {item.operation_id for item in self.operations}
        if len(operation_ids) != len(self.operations):
            raise ValueError("task_semantic_invalid: operation ids must be unique")
        previous = set()
        for operation in self.operations:
            refs = {value for value in (operation.source, operation.destination, operation.target, operation.reference) if value}
            unknown = {value for value in refs if not known_reference(value)}
            if unknown:
                raise ValueError(f"task_semantic_invalid: operation references unknown entities: {sorted(unknown)}")
            if not set(operation.depends_on) <= previous:
                raise ValueError("task_semantic_invalid: invalid operation depends_on")
            previous.add(operation.operation_id)
            if (operation.placement_target and operation.placement_target.reference
                    and not known_reference(operation.placement_target.reference)):
                raise ValueError("task_semantic_invalid: unknown placement reference")
        for relation in self.spatial_relations:
            if relation.subject not in entity_ids or (relation.reference and not known_reference(relation.reference)):
                raise ValueError("task_semantic_invalid: spatial relation references unknown entities")
        return self

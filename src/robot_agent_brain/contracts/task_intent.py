from __future__ import annotations

from enum import StrEnum
from typing import Literal
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
    tags: list[str] = Field(default_factory=list)
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
    arm: Literal["left", "right", "single"] | None = None
    parallel_group: str | None = Field(default=None, min_length=1)
    parallel_required: bool = False
    assignment_mode: str = Field(default="broadcast", pattern=r"^(broadcast|pairwise|repeat_all|relation_matched)$")

    @model_validator(mode="after")
    def validate_operation(self):
        if self.parallel_required and self.parallel_group is None:
            raise ValueError("task_semantic_invalid: parallel_required needs parallel_group")
        from ..semantics.operation_contracts import validate_operation_contract
        validate_operation_contract(self)
        return self


class TaskHoldConstraint(StrictModel):
    kind: Literal["hold_during_operation", "hold_until_operation"]
    holder_arm: Literal["left", "right"]
    object_entity: str
    while_operation: str
    holder_operation: str | None = None
    region_entity: str | None = None
    region: Literal["placement_region"] | None = None

    @model_validator(mode="after")
    def complete_milestone(self):
        if (self.region is None) != (self.region_entity is None):
            raise ValueError("dual_hold_region_incomplete")
        if self.kind == "hold_until_operation" and (self.holder_operation is None or self.region is None):
            raise ValueError("dual_hold_milestone_incomplete")
        if self.kind == "hold_during_operation" and self.holder_operation is not None:
            raise ValueError("dual_hold_unexpected_holder_operation")
        return self


class TaskIntent(StrictModel):
    instruction: str = Field(min_length=1)
    arm_usage: Literal["unspecified", "both_required"] = "unspecified"
    hold_constraints: list[TaskHoldConstraint] = Field(default_factory=list)
    entities: list[TaskEntity]
    operations: list[Operation]
    spatial_relations: list[SpatialRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
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
        for hold in self.hold_constraints:
            if (hold.object_entity not in entity_ids or hold.region_entity is not None and hold.region_entity not in entity_ids
                    or hold.while_operation not in operation_ids
                    or hold.holder_operation is not None and hold.holder_operation not in operation_ids):
                raise ValueError("task_semantic_invalid: hold constraint reference missing")
        previous = set()
        groups = {}
        closed_groups = set()
        active_group = None
        for operation in self.operations:
            if operation.parallel_group != active_group:
                if active_group is not None:
                    closed_groups.add(active_group)
                if operation.parallel_group in closed_groups:
                    raise ValueError("task_semantic_invalid: parallel group must be contiguous")
                active_group = operation.parallel_group
            if operation.parallel_group is not None:
                peers = groups.setdefault(operation.parallel_group, set())
                if peers.intersection(operation.depends_on):
                    raise ValueError("task_semantic_invalid: parallel dependency conflict")
                peers.add(operation.operation_id)
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

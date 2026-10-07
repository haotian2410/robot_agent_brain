from __future__ import annotations
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .task_intent import TaskIntent, TaskEntity, Direction, MotionScale
from .spatial import SpatialRelation

class TurnStatus(StrEnum):
    ACCEPTED = "accepted"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED_TASK = "unsupported_task"

class TurnKind(StrEnum):
    ROBOT_TASK = "robot_task"
    SCENE_EDIT = "scene_edit"
    SCENE_QUERY = "scene_query"
    SESSION_CONTROL = "session_control"
    UNSUPPORTED_TASK = "unsupported_task"

class SceneEditIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["add", "remove", "translate", "rotate", "move_relative", "update_properties", "update"]
    semantic_name: str = ""
    category: str = ""
    target: str | None = None
    count: int = Field(default=1, ge=1)
    relation: str | None = None
    reference: str | None = None
    properties: dict[str, str | float | bool] = Field(default_factory=dict)
    direction: Direction | None = None
    distance_m: float | None = Field(default=None, gt=0, le=2)
    motion_scale: MotionScale | None = None
    coordinate_frame: Literal["world", "object_local"] = "world"
    axis: Literal["x", "y", "z"] | None = None
    angle_deg: float | None = None
    pivot: Literal["origin"] = "origin"
    explicit_robot: bool = False

    @model_validator(mode="after")
    def paired_relation(self):
        if not self.target and not (self.semantic_name and self.category):
            raise ValueError("scene edit needs a target selector or legacy name/category")
        if (self.relation is None) != (self.reference is None):
            raise ValueError("task_semantic_invalid: scene edit relation/reference must be paired")
        if self.operation in {"translate", "move_relative"} and not (self.direction or self.relation):
            raise ValueError("task_semantic_invalid: translation requires direction or relation")
        if self.operation == "rotate" and (self.axis is None or self.angle_deg is None):
            raise ValueError("task_semantic_invalid: rotation requires axis and angle")
        fields = {
            "relation": self.relation, "reference": self.reference,
            "direction": self.direction, "distance_m": self.distance_m,
            "motion_scale": self.motion_scale, "axis": self.axis, "angle_deg": self.angle_deg,
        }
        allowed = {
            "add": {"relation", "reference"}, "remove": set(),
            "translate": {"direction", "distance_m", "motion_scale"},
            "move_relative": {"relation", "reference"},
            "rotate": {"axis", "angle_deg"}, "update_properties": set(),
            "update": {"relation", "reference"},  # legacy layout/property edit
        }[self.operation]
        if any(value is not None and key not in allowed for key, value in fields.items()):
            raise ValueError(f"scene_edit_fields_forbidden: {self.operation}")
        if self.operation == "move_relative" and self.reference is None:
            raise ValueError("scene_edit_relative_reference_missing")
        if self.operation == "translate" and self.distance_m is not None and self.motion_scale is not None:
            raise ValueError("scene_edit_distance_modes_exclusive")
        if self.properties and self.operation not in {"add", "update", "update_properties"}:
            raise ValueError("scene_edit_properties_forbidden")
        if self.operation not in {"translate", "rotate"} and self.coordinate_frame != "world":
            raise ValueError("scene_edit_coordinate_frame_forbidden")
        return self


class SceneEditPlan(BaseModel):
    """Ordered edits sharing the same entity/selection contract as robot tasks."""
    model_config = ConfigDict(extra="forbid")
    entities: list[TaskEntity] = Field(default_factory=list)
    relations: list[SpatialRelation] = Field(default_factory=list)
    operations: list[SceneEditIntent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_selectors(self):
        TaskIntent(instruction="scene selection", entities=self.entities,
                   operations=[], spatial_relations=self.relations)
        ids = {entity.entity_id for entity in self.entities}
        for op in self.operations:
            if op.target and op.target not in ids:
                raise ValueError("scene_edit_unknown_selector")
            if op.reference and op.target and op.reference not in ids:
                raise ValueError("scene_edit_unknown_reference_selector")
        return self

class SceneQueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: Literal["count", "existence", "position", "state"]
    entities: list[TaskEntity] = Field(min_length=1)
    relations: list[SpatialRelation] = Field(default_factory=list)
    target: str

    @model_validator(mode="after")
    def query_selectors(self):
        TaskIntent(instruction="query", entities=self.entities, operations=[], spatial_relations=self.relations)
        if self.target not in {e.entity_id for e in self.entities}:
            raise ValueError("query_target_missing")
        if any(r.scope != "selection" for r in self.relations):
            raise ValueError("query_requires_selection_relations")
        return self

class SessionControlIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "close"]

class BrainTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TurnStatus
    turn_kind: TurnKind
    instruction: str
    task_intent: TaskIntent | None = None
    scene_edit: SceneEditPlan | SceneEditIntent | None = None
    scene_query: SceneQueryIntent | None = None
    session_control: SessionControlIntent | None = None

    @model_validator(mode="after")
    def one_payload(self):
        payloads = {
            TurnKind.ROBOT_TASK: self.task_intent,
            TurnKind.SCENE_EDIT: self.scene_edit,
            TurnKind.SCENE_QUERY: self.scene_query,
            TurnKind.SESSION_CONTROL: self.session_control,
        }
        if self.status != TurnStatus.ACCEPTED:
            if any(value is not None for value in payloads.values()):
                raise ValueError("rejected turn must not contain actionable payloads")
            return self
        if self.turn_kind == TurnKind.UNSUPPORTED_TASK:
            raise ValueError("unsupported turn must have unsupported_task status")
        if self.turn_kind in payloads and payloads[self.turn_kind] is None:
            raise ValueError("turn payload is missing")
        if self.turn_kind in payloads and sum(value is not None for value in (self.task_intent, self.scene_edit, self.scene_query, self.session_control)) != 1:
            raise ValueError("turn must contain exactly one payload")
        return self

from __future__ import annotations
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .task_intent import TaskIntent, TaskEntity, Direction, MotionScale
from .spatial import SpatialRelation
from .robot_setup import RobotSetupRequest

class TurnStatus(StrEnum):
    ACCEPTED = "accepted"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED_TASK = "unsupported_task"

class TurnKind(StrEnum):
    ROBOT_CONFIG = "robot_config"
    ROBOT_TASK = "robot_task"
    SCENE_EDIT = "scene_edit"
    SCENE_QUERY = "scene_query"
    SESSION_CONTROL = "session_control"
    UNSUPPORTED_TASK = "unsupported_task"


class SceneLayoutRelation(StrEnum):
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    FRONT_OF = "front_of"
    BEHIND = "behind"
    ABOVE = "above"
    BELOW = "below"
    NEAR = "near"
    ON = "on"
    INSIDE = "inside"


_SCENE_LAYOUT_RELATION_ALIASES = {
    "back_of": SceneLayoutRelation.BEHIND,
    "back": SceneLayoutRelation.BEHIND,
    "后面": SceneLayoutRelation.BEHIND,
    "后方": SceneLayoutRelation.BEHIND,
}

class SceneEditIntent(BaseModel):
    """One operation in a SceneEditPlan; never a standalone turn payload."""
    model_config = ConfigDict(extra="forbid")
    operation: Literal["add", "remove", "replace", "translate", "rotate", "move_relative", "update_properties", "update", "scale"]
    replacement_entity: str | None = None
    scale_mode: Literal["multiply", "set"] | None = None
    scale_xyz: tuple[float, float, float] | None = None
    scale_direction: Literal["enlarge", "shrink"] | None = None
    scale_amount: Literal["small", "medium", "large"] | None = None
    # Placement controls are deliberately separate from generic properties.
    # ``center`` is a hard constraint; ``any`` permits deterministic grid search.
    placement_hint: Literal["center", "any"] | None = None
    placement_region: Literal[
        "left_half", "right_half", "front_half", "back_half",
        "left_front", "right_front", "left_back", "right_back",
    ] | None = None
    target: str = Field(min_length=1)
    relation: SceneLayoutRelation | None = None
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

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_position_hint(cls, values):
        """Accept the one historical Qwen field without opening arbitrary props.

        Older prompts occasionally emitted ``properties.position_hint`` for a
        centered placement.  It is a semantic placement control, not a Scene
        component property, so normalize only the exact supported value.
        """
        if not isinstance(values, dict):
            return values
        props = values.get("properties")
        if isinstance(props, dict) and "position_hint" in props:
            value = props.get("position_hint")
            if value != "center":
                raise ValueError("scene_edit_properties_unsupported: position_hint must be center")
            if values.get("placement_hint") not in (None, "center"):
                raise ValueError("scene_edit_placement_hint_conflict")
            values = dict(values)
            values["placement_hint"] = values.get("placement_hint") or "center"
            new_props = dict(props)
            new_props.pop("position_hint", None)
            values["properties"] = new_props
        return values

    @field_validator("relation", mode="before")
    @classmethod
    def normalize_relation(cls, value):
        if value is None or isinstance(value, SceneLayoutRelation):
            return value
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold()
        return _SCENE_LAYOUT_RELATION_ALIASES.get(normalized, normalized)

    @model_validator(mode="after")
    def paired_relation(self):
        import math
        if (self.operation == "replace") != (self.replacement_entity is not None):
            raise ValueError("scene_replace_entity_required_or_forbidden")
        if self.replacement_entity == self.target:
            raise ValueError("scene_replace_requires_distinct_entities")
        scale_fields = (self.scale_mode, self.scale_xyz, self.scale_direction, self.scale_amount)
        if self.operation == "scale":
            numeric = self.scale_mode is not None and self.scale_xyz is not None and self.scale_direction is None and self.scale_amount is None
            fuzzy = self.scale_mode is None and self.scale_xyz is None and self.scale_direction is not None and self.scale_amount is not None
            if not (numeric or fuzzy):
                raise ValueError("scene_scale_modes_exclusive")
            if self.scale_xyz is not None and not all(math.isfinite(v) and v > 0 for v in self.scale_xyz):
                raise ValueError("scene_scale_invalid")
        elif any(v is not None for v in scale_fields):
            raise ValueError("scene_edit_fields_forbidden: scale")
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
            "add": {"relation", "reference"}, "remove": set(), "replace": set(),
            "translate": {"direction", "distance_m", "motion_scale"},
            "move_relative": {"relation", "reference"},
            "rotate": {"axis", "angle_deg"}, "update_properties": set(), "scale": set(),
            "update": {"relation", "reference"},  # combined layout/property operation
        }[self.operation]
        if any(value is not None and key not in allowed for key, value in fields.items()):
            raise ValueError(f"scene_edit_fields_forbidden: {self.operation}")
        if self.placement_hint is not None or self.placement_region is not None:
            if self.operation not in {"add", "move_relative", "update"}:
                raise ValueError(f"scene_edit_fields_forbidden: {self.operation}")
            if self.placement_region is not None and self.relation != SceneLayoutRelation.ON:
                raise ValueError("scene_edit_placement_region_requires_on")
        if self.relation == SceneLayoutRelation.ON and self.operation in {"add", "move_relative", "update"}:
            # A missing hint means ordinary placement and is intentionally
            # handled as ``any`` by the deterministic Python grid policy.
            pass
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
    scene_basis: Literal["current", "original"] = "current"
    entities: list[TaskEntity] = Field(min_length=1)
    relations: list[SpatialRelation] = Field(default_factory=list)
    operations: list[SceneEditIntent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_selectors(self):
        TaskIntent(instruction="scene selection", entities=self.entities,
                   operations=[], spatial_relations=self.relations)
        ids = {entity.entity_id for entity in self.entities}
        for identifier in ids:
            selectors = [r for r in self.relations if r.subject == identifier and r.scope == "selection"]
            for reference in {r.reference for r in selectors}:
                kinds = {r.relation.value for r in selectors if r.reference == reference}
                if any({a,b} <= kinds for a,b in [("leftmost","rightmost"),("frontmost","backmost"),
                                                 ("highest","lowest"),("nearest","farthest")]):
                    raise ValueError("scene_edit_selection_conflict: opposing extrema require distinct entity roles")
        for op in self.operations:
            if op.target not in ids:
                raise ValueError("scene_edit_unknown_selector")
            if op.replacement_entity is not None and op.replacement_entity not in ids:
                raise ValueError("scene_replace_unknown_entity")
            if op.reference and op.reference not in ids:
                raise ValueError("scene_edit_unknown_reference_selector")
        return self

    def validate_semantics(self, *, allow_unresolved_references=False):
        """Validate cross-field selectors after wire normalization.

        Direct callers retain the historical strict model validation above.  The
        live Qwen adapter uses ``model_construct`` for a canonical plan and then
        calls this method, so an environment reference such as ``table`` can be
        resolved by the scene resolver instead of being mistaken for an entity.
        """
        ids = {entity.entity_id for entity in self.entities}
        for op in self.operations:
            if op.target not in ids:
                raise ValueError("scene_edit_unknown_selector: " + op.target)
            if op.replacement_entity is not None and op.replacement_entity not in ids:
                raise ValueError("scene_replace_unknown_entity: " + op.replacement_entity)
            if op.reference and op.reference not in ids and not allow_unresolved_references:
                raise ValueError("scene_edit_unknown_reference_selector: " + op.reference)
        return self

class SceneQueryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_type: Literal["count", "existence", "position", "state", "neighbors", "relation", "selection"]
    entities: list[TaskEntity] = Field(min_length=1)
    relations: list[SpatialRelation] = Field(default_factory=list)
    target: str
    reference: str | None = None
    predicate: Literal["left_of", "right_of", "front_of", "behind", "above", "below", "on"] | None = None
    evidence_source: Literal["scene", "image"] = "scene"

    @model_validator(mode="after")
    def query_selectors(self):
        TaskIntent(instruction="query", entities=self.entities, operations=[], spatial_relations=self.relations)
        if self.target not in {e.entity_id for e in self.entities}:
            raise ValueError("query_target_missing")
        if any(r.scope != "selection" for r in self.relations):
            raise ValueError("query_requires_selection_relations")
        if self.query_type == "selection" and not any(r.subject == self.target for r in self.relations):
            raise ValueError("query_selection_requires_explicit_selector")
        if self.query_type == "relation":
            if self.reference is None or self.predicate is None:
                raise ValueError("query_relation_requires_reference_and_predicate")
            SpatialRelation(scope="selection", subject=self.target, reference=self.reference, relation=self.predicate)
            if self.reference not in {e.entity_id for e in self.entities}:
                raise ValueError("query_reference_missing")
        elif self.reference is not None or self.predicate is not None:
            raise ValueError("query_predicate_requires_relation_query")
        return self

class SessionControlIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "resume", "close"]

class BrainTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TurnStatus
    turn_kind: TurnKind
    instruction: str
    clarification_question: str | None = None
    task_intent: TaskIntent | None = None
    scene_edit: SceneEditPlan | None = None
    scene_query: SceneQueryIntent | None = None
    session_control: SessionControlIntent | None = None
    robot_setup_request: RobotSetupRequest | None = None

    def require_legacy_execution(self):
        """Temporary fail-closed boundary until session v3 routing is installed."""
        if self.status != TurnStatus.ACCEPTED:
            return
        if self.robot_setup_request is not None or self.turn_kind == TurnKind.ROBOT_CONFIG:
            raise ValueError("robot_setup_profile_not_registered")
        if self.task_intent and (self.task_intent.arm_usage == "both_required" or self.task_intent.hold_constraints or
                                any(op.arm in {"left", "right"} or op.parallel_group is not None
                                    for op in self.task_intent.operations)):
            raise ValueError("dual_arm_execution_not_configured")

    @model_validator(mode="after")
    def one_payload(self):
        if self.status == TurnStatus.ACCEPTED and self.clarification_question is not None:
            raise ValueError("accepted turn cannot contain clarification_question")
        payloads = {
            TurnKind.ROBOT_CONFIG: self.robot_setup_request,
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
        if self.robot_setup_request is not None and self.turn_kind not in {TurnKind.ROBOT_CONFIG, TurnKind.ROBOT_TASK}:
            raise ValueError("robot_setup_request_requires_robot_turn")
        if self.turn_kind in payloads and payloads[self.turn_kind] is None:
            raise ValueError("turn payload is missing")
        expected = 2 if self.turn_kind == TurnKind.ROBOT_TASK and self.robot_setup_request is not None else 1
        if sum(value is not None for value in payloads.values()) != expected:
            raise ValueError("turn must contain exactly one payload")
        return self

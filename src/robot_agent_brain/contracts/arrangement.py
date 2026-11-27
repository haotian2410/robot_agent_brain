"""Stable intermediate contract for user-authored scene arrangements.

This contract deliberately stops before scene object allocation.  It is safe to
serialize in a task-understanding result and keeps world coordinates, IDs and
robot skills out of the model-facing payload.
"""
from __future__ import annotations

from typing import Literal
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArrangementStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PatternKind = Literal[
    "line", "grid", "circle", "ring", "arc", "checker", "alternating",
    "scatter", "text", "custom",
]
ArrangementOperation = Literal["create", "append", "rearrange", "replace"]
ArrangementBasis = Literal["current", "original"]
ItemsMode = Literal["single", "sequence", "counts"]
CountMode = Literal["exact", "at_least", "auto"]
RegionKind = Literal["surface_region", "around", "near", "relative"]
ANCHOR_REGION_KINDS = frozenset({"around", "near", "relative"})
SpacingMode = Literal["center", "edge", "auto"]
OrientationMode = Literal["fixed", "follow_pattern"]

# One parameter policy shared by canonical validation and model wire grammar.
PATTERN_FIELDS = {
    "line": {"axis"}, "alternating": {"axis"},
    "grid": {"rows", "cols", "order", "axis"},
    "checker": {"rows", "cols", "order", "axis"},
    "circle": {"radius_m", "order"},
    "ring": {"inner_radius_m", "outer_radius_m", "order"},
    "arc": {"radius_m", "angle_span_deg", "order"},
    "scatter": set(), "text": {"text", "font", "path"}, "custom": {"path"},
}
PATTERN_REQUIRED = {
    "ring": (("inner_radius_m", "outer_radius_m"),),
    "arc": (("radius_m", "angle_span_deg"),), "text": (("text",),),
    "custom": (("description",), ("path",)),
}


class ArrangementPattern(ArrangementStrictModel):
    kind: PatternKind
    rows: int | None = Field(default=None, strict=True, ge=1, le=100)
    cols: int | None = Field(default=None, strict=True, ge=1, le=100)
    order: Literal["row_major", "column_major", "clockwise"] = "row_major"
    axis: Literal["x", "y"] | None = None
    radius_m: float | None = Field(default=None, gt=0, le=10)
    inner_radius_m: float | None = Field(default=None, gt=0, le=10)
    outer_radius_m: float | None = Field(default=None, gt=0, le=10)
    angle_span_deg: float | None = Field(default=None, gt=0, le=360)
    text: str | None = Field(default=None, min_length=1, max_length=128)
    font: str = Field(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    path: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def validate_parameters(self):
        allowed = PATTERN_FIELDS[self.kind] | {"kind", "description"}
        for field, definition in type(self).model_fields.items():
            if field not in allowed and getattr(self, field) != definition.default:
                raise ValueError(f"scene_layout_pattern_field_forbidden:{self.kind}.{field}")
        if self.kind == "ring" and (self.inner_radius_m is None or self.outer_radius_m is None):
            raise ValueError("scene_layout_ring_radius_missing")
        if self.kind == "ring" and self.inner_radius_m >= self.outer_radius_m:
            raise ValueError("scene_layout_ring_radius_invalid")
        if self.kind == "arc" and (self.radius_m is None or self.angle_span_deg is None):
            raise ValueError("scene_layout_arc_parameters_missing")
        if self.kind == "text" and not self.text:
            raise ValueError("scene_layout_text_missing")
        if self.kind == "custom" and not self.description and not self.path:
            raise ValueError("scene_layout_custom_description_missing")
        if self.path is not None:
            if len(self.path) > 512:
                raise ValueError("scene_layout_path_too_long")
            for u, v in self.path:
                if not math.isfinite(u) or not math.isfinite(v) or not (0 <= u <= 1 and 0 <= v <= 1):
                    raise ValueError("scene_layout_path_out_of_range")
            from .layout_path import validate_simple_path
            validate_simple_path(self.path)
        return self


class ArrangementItem(ArrangementStrictModel):
    alias: str = Field(min_length=1)
    count: int = Field(default=1, strict=True, ge=1, le=1000)


class ArrangementItems(ArrangementStrictModel):
    mode: ItemsMode = "single"
    assets: list[ArrangementItem] = Field(min_length=1)
    requested_count: int = Field(strict=True, ge=1, le=1000)
    count_mode: CountMode = "exact"
    sequence: list[str] | None = None
    auto_count: bool = Field(default=False, strict=True)
    min_count: int | None = Field(default=None, strict=True, ge=1, le=1000)
    max_count: int | None = Field(default=None, strict=True, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_count(self):
        if self.mode == "single" and len(self.assets) != 1:
            raise ValueError("scene_layout_single_requires_one_asset")
        if self.mode == "sequence" and not self.sequence:
            raise ValueError("scene_layout_sequence_missing")
        if self.count_mode == "auto" and not self.auto_count:
            raise ValueError("scene_layout_auto_count_not_authorized")
        if (self.min_count is None) != (self.max_count is None):
            raise ValueError("scene_layout_count_bounds_incomplete")
        if self.min_count is not None:
            if self.count_mode != "auto" or not self.auto_count:
                raise ValueError("scene_layout_count_bounds_not_authorized")
            if not self.min_count <= self.requested_count <= self.max_count:
                raise ValueError("scene_layout_count_outside_bounds")
        if self.count_mode == "exact" and self.requested_count < 1:
            raise ValueError("scene_layout_count_invalid")
        return self


class ArrangementRegion(ArrangementStrictModel):
    kind: RegionKind = "surface_region"
    surface_ref: str = Field(min_length=1)
    anchor_ref: str | None = None
    side: Literal["left_half", "right_half", "front_half", "back_half", "center", "any"] = "center"
    width_m: float | None = Field(default=None, gt=0, le=10)
    depth_m: float | None = Field(default=None, gt=0, le=10)
    margin_m: float = Field(default=0.03, ge=0, le=1)

    @model_validator(mode="after")
    def validate_anchor(self):
        if self.kind in ANCHOR_REGION_KINDS and not self.anchor_ref:
            raise ValueError("scene_layout_anchor_missing")
        if self.kind not in ANCHOR_REGION_KINDS and self.anchor_ref is not None:
            raise ValueError("scene_layout_anchor_forbidden")
        if self.kind == "relative" and self.side in {"center", "any"}:
            raise ValueError("scene_layout_relative_direction_missing")
        return self


class ArrangementSpacing(ArrangementStrictModel):
    mode: SpacingMode = "center"
    value_m: float | None = Field(default=None, gt=0, le=10)
    auto: bool = False

    @model_validator(mode="after")
    def validate_auto(self):
        if self.mode == "auto" and self.value_m is not None:
            raise ValueError("scene_layout_spacing_auto_value_conflict")
        if self.mode == "auto" and not self.auto:
            raise ValueError("scene_layout_spacing_auto_not_authorized")
        if self.mode != "auto" and self.auto:
            raise ValueError("scene_layout_spacing_auto_conflict")
        if self.mode != "auto" and self.value_m is None:
            raise ValueError("scene_layout_spacing_value_missing")
        return self


class ArrangementOrientation(ArrangementStrictModel):
    mode: OrientationMode = "fixed"
    yaw_deg: float = 0.0


class ArrangementConstraints(ArrangementStrictModel):
    support: Literal["on_surface", "inside", "free_space"] = "on_surface"
    keep_inside_region: bool = True
    avoid_existing: bool = True
    min_clearance_m: float = Field(default=0.01, ge=0, le=1)
    allow_scale: bool = False


class ArrangementSpec(ArrangementStrictModel):
    arrangement_id: str = Field(min_length=1, pattern=r"^arr-[A-Za-z0-9_-]+$")
    operation: ArrangementOperation = "create"
    basis: ArrangementBasis = "current"
    pattern: ArrangementPattern
    items: ArrangementItems
    region: ArrangementRegion
    spacing: ArrangementSpacing
    orientation: ArrangementOrientation = Field(default_factory=ArrangementOrientation)
    constraints: ArrangementConstraints = Field(default_factory=ArrangementConstraints)
    seed: int | None = None
    source: Literal["user", "replay", "planner"] = "user"

    @model_validator(mode="after")
    def validate_pattern_count(self):
        if (self.pattern.kind == "circle" and self.pattern.radius_m is None
                and not (self.spacing.mode == "auto" and self.spacing.auto)):
            raise ValueError("scene_layout_circle_radius_missing")
        if self.pattern.kind in {"grid", "checker"} and self.pattern.rows and self.pattern.cols:
            slots = self.pattern.rows * self.pattern.cols
            if self.items.count_mode == "exact" and slots != self.items.requested_count:
                raise ValueError("scene_layout_count_conflict")
        return self


class LayoutSlot(ArrangementStrictModel):
    slot_id: str = Field(pattern=r"^s[0-9]+$")
    u: float = Field(ge=0, le=1)
    v: float = Field(ge=0, le=1)
    index: int = Field(ge=0)


class LayoutPlan(ArrangementStrictModel):
    arrangement_id: str = Field(min_length=1)
    pattern_kind: PatternKind
    slot_frame: Literal["normalized_region_2d"] = "normalized_region_2d"
    slots: list[LayoutSlot] = Field(min_length=1, max_length=1000)
    orientation_hints: list[float] = Field(default_factory=list)
    planner_source: Literal["deterministic", "qwen_draft"] = "deterministic"
    planner_revision: str = "layout-planner-v1"
    effective_seed: int | None = None

    @model_validator(mode="after")
    def validate_slots(self):
        ids = [slot.slot_id for slot in self.slots]
        if len(ids) != len(set(ids)) or len({slot.index for slot in self.slots}) != len(self.slots):
            raise ValueError("scene_layout_duplicate_slot")
        if len({(slot.u, slot.v) for slot in self.slots}) != len(self.slots):
            raise ValueError("scene_layout_duplicate_slot_position")
        if self.orientation_hints and len(self.orientation_hints) != len(self.slots):
            raise ValueError("scene_layout_orientation_count_mismatch")
        if any(not math.isfinite(value) for value in self.orientation_hints):
            raise ValueError("scene_layout_orientation_invalid")
        return self


class LayoutResolution(ArrangementStrictModel):
    arrangement_id: str
    scene_id: int
    scene_version: int = Field(ge=0)
    instance_ids: list[int] = Field(min_length=1)
    slot_bindings: dict[str, int]
    slot_assets: dict[str, str] = Field(default_factory=dict)
    # Optional world-space projection produced by the resolver.  Keeping this
    # separate from Scene v1 means layout metadata can be audited without
    # teaching the model to emit coordinates.
    world_positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    adjusted_spacing_m: float | None = None
    assumptions: list[str] = Field(default_factory=list)

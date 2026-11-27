"""ArrangementSpec -> normalized LayoutPlan.

Known patterns never call a model.  Custom/text plans are deliberately
restricted and must provide a normalized path before they can be accepted.
"""
from __future__ import annotations
import math
import hashlib
import json

from ..contracts.arrangement import ArrangementSpec, LayoutPlan, LayoutSlot
from .layout_pattern_registry import PATTERN_GENERATORS, supported_pattern, grid_cells


def expanded_count(spec: ArrangementSpec) -> int:
    return len(expanded_aliases(spec))


def expanded_aliases(spec: ArrangementSpec) -> list[str]:
    """One shared count expansion for planning, instantiation and auditing.

    Single repeats one asset; counts preserves every per-asset count; an
    explicit sequence is exact unless the pattern explicitly requests cycling.
    Capacity adaptation must happen elsewhere with recorded authorization.
    """
    items = spec.items
    count = items.requested_count
    explicit_grid = (spec.pattern.kind in {"grid", "checker"}
                     and spec.pattern.rows is not None and spec.pattern.cols is not None)
    if (items.count_mode == "at_least" and spec.pattern.kind in {"grid", "checker"}
            and spec.pattern.rows is not None and spec.pattern.cols is not None):
        cells = spec.pattern.rows * spec.pattern.cols
        if cells < count:
            raise ValueError("scene_layout_count_conflict")
        if cells > 1000:
            raise ValueError("scene_layout_count_limit_exceeded")
        count = cells
    if items.mode == "single":
        item = items.assets[0]
        if item.count not in (1, items.requested_count, count):
            raise ValueError("scene_layout_count_conflict")
        return [item.alias] * count
    if items.mode == "sequence":
        aliases = list(items.sequence or [])
        if not aliases or not set(aliases) <= {item.alias for item in items.assets}:
            raise ValueError("scene_layout_asset_unresolved")
        if spec.pattern.kind == "checker":
            _, _, cells = grid_cells(spec, count)
            return [aliases[(row + col) % len(aliases)] for row, col in cells]
        if spec.pattern.kind == "alternating":
            return [aliases[index % len(aliases)] for index in range(count)]
    else:
        if sum(item.count for item in items.assets) > 1000:
            raise ValueError("scene_layout_count_limit_exceeded")
        aliases = [item.alias for item in items.assets for _ in range(item.count)]
    if len(aliases) > 1000:
        raise ValueError("scene_layout_count_limit_exceeded")
    if items.count_mode == "at_least" and not explicit_grid:
        if len(aliases) < count:
            raise ValueError("scene_layout_count_conflict")
        return aliases
    if len(aliases) != count:
        raise ValueError("scene_layout_count_conflict")
    return aliases


def plan_arrangement(spec: ArrangementSpec, *, font_registry=None) -> LayoutPlan:
    count = expanded_count(spec)
    kind = spec.pattern.kind
    effective_seed = spec.seed
    planner_revision = "layout-planner-v1"
    if kind == "scatter" and effective_seed is None:
        # Stable across retries and processes, unlike Python's salted hash().
        # Include arrangement identity so different arrangements can vary.
        material = json.dumps(spec.model_dump(mode="json"), sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        effective_seed = int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")
        spec = spec.model_copy(update={"seed": effective_seed})
    if not supported_pattern(kind):
        raise ValueError("scene_layout_pattern_unsupported")
    if kind in PATTERN_GENERATORS:
        points = PATTERN_GENERATORS[kind](spec, count)
    elif kind == "text" and not spec.pattern.path:
        from .text_layout import text_slots
        font_path = (font_registry or {}).get(spec.pattern.font)
        if font_path is None:
            raise ValueError("scene_layout_font_unregistered: " + spec.pattern.font)
        points, fingerprint = text_slots(spec.pattern.text, count, font_path)
        planner_revision = "font-outline-v1:" + fingerprint
    elif spec.pattern.path:
        from .layout_path_sampler import sample_polyline
        points = sample_polyline(spec.pattern.path, count)
    else:
        raise ValueError("scene_layout_custom_requires_normalized_path")
    slots = [LayoutSlot(slot_id=f"s{i}", u=float(u), v=float(v), index=i)
             for i, (u, v) in enumerate(points)]
    return LayoutPlan(arrangement_id=spec.arrangement_id, pattern_kind=kind,
                      planner_revision=planner_revision,
                      effective_seed=effective_seed,
                      slots=slots, orientation_hints=pattern_yaws(spec, points),
                      planner_source="deterministic")


def pattern_yaws(spec, points, *, scale=(1., 1.)):
    """Return deterministic yaw degrees; scale converts path tangents to region axes."""
    offset = spec.orientation.yaw_deg
    if spec.orientation.mode == "fixed":
        return [offset] * len(points)
    kind = spec.pattern.kind
    if kind in {"circle", "ring", "arc"}:
        tangent = -90 if spec.pattern.order == "clockwise" else 90
        return [math.degrees(math.atan2(v - .5, u - .5)) + tangent + offset for u, v in points]
    if kind in {"line", "alternating", "grid", "checker"}:
        yaw = 90 if spec.pattern.axis == "y" else 0
        return [yaw + offset] * len(points)
    if kind == "scatter" or len(points) < 2:
        raise ValueError("scene_layout_orientation_ambiguous")
    result = []
    for index in range(len(points)):
        a, b = (points[index], points[index + 1]) if index + 1 < len(points) else (points[-2], points[-1])
        result.append(math.degrees(math.atan2((b[1] - a[1]) * scale[1],
                                             (b[0] - a[0]) * scale[0])) + offset)
    return result

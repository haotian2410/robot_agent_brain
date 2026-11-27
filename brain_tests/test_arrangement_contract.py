import pytest
from pydantic import ValidationError

from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.planning.layout_planner import plan_arrangement
from robot_agent_brain.scene.layout_resolver import LayoutResolver


def spec(kind="grid", count=4, **kwargs):
    pattern = {"kind": kind, "rows": 2, "cols": 2} if kind == "grid" else {"kind": kind, "radius_m": .1}
    return ArrangementSpec(
        arrangement_id="arr-test", pattern=pattern,
        items={"mode": "single", "assets": [{"alias": "apple"}], "requested_count": count},
        region={"surface_ref": "table", "side": "center"},
        spacing={"mode": "center", "value_m": .05}, **kwargs)


def test_grid_is_deterministic_and_normalized():
    first = plan_arrangement(spec())
    second = plan_arrangement(spec())
    assert first.model_dump() == second.model_dump()
    assert [slot.slot_id for slot in first.slots] == ["s0", "s1", "s2", "s3"]
    assert all(0 <= slot.u <= 1 and 0 <= slot.v <= 1 for slot in first.slots)


@pytest.mark.parametrize("side", ["center", "any"])
def test_relative_region_requires_explicit_direction(side):
    data = spec().model_dump()
    data["region"].update(kind="relative", anchor_ref="basket", side=side)
    with pytest.raises(ValidationError, match="relative_direction_missing"):
        ArrangementSpec.model_validate(data)


def test_invalid_grid_count_is_rejected():
    with pytest.raises(ValidationError):
        spec(count=3)


def test_authorized_quantity_bounds_survive_compact_roundtrip():
    from robot_agent_brain.models.understanding_wire import encode, decode
    data = spec().model_dump(mode="json")
    data["items"].update(count_mode="auto", auto_count=True, min_count=2, max_count=8)
    canonical = ArrangementSpec.model_validate(data)
    wire = encode({"status": "accepted", "turn_kind": "scene_layout",
                   "arrangement_spec": canonical.model_dump(mode="json")})
    expanded = decode(wire)
    assert expanded["arrangement_spec"]["items"]["min_count"] == 2
    assert expanded["arrangement_spec"]["items"]["max_count"] == 8
    assert ArrangementSpec.model_validate(expanded["arrangement_spec"]) == canonical


@pytest.mark.parametrize("changes", [
    {"min_count": 2}, {"max_count": 8}, {"min_count": 5, "max_count": 8},
    {"min_count": 1, "max_count": 3}, {"min_count": 8, "max_count": 2},
    {"min_count": True, "max_count": 8}, {"min_count": 2, "max_count": 8.0},
    {"min_count": 2, "max_count": 8, "count_mode": "exact"},
])
def test_quantity_bounds_are_paired_strict_and_authorized(changes):
    data = spec().model_dump()
    data["items"].update({"count_mode": "auto", "auto_count": True, **changes})
    with pytest.raises(ValidationError):
        ArrangementSpec.model_validate(data)


@pytest.mark.parametrize("mode", ["counts", "sequence"])
def test_at_least_preserves_explicit_asset_totals_without_inventing_members(mode):
    from robot_agent_brain.planning.layout_planner import expanded_aliases
    data = spec().model_dump()
    data["pattern"] = {"kind": "line"}
    data["items"] = {"mode": mode, "assets": [{"alias": "apple", "count": 3},
                                               {"alias": "banana", "count": 3}],
                     "requested_count": 5, "count_mode": "at_least"}
    if mode == "sequence":
        data["items"]["sequence"] = ["apple", "banana"] * 3
    value = ArrangementSpec.model_validate(data)
    assert len(plan_arrangement(value).slots) == 6
    assert expanded_aliases(value).count("apple") == expanded_aliases(value).count("banana") == 3
    data["items"]["requested_count"] = 7
    with pytest.raises(ValueError, match="count_conflict"):
        plan_arrangement(ArrangementSpec.model_validate(data))
    data["items"].update(requested_count=5, count_mode="exact")
    with pytest.raises(ValueError, match="count_conflict"):
        plan_arrangement(ArrangementSpec.model_validate(data))


def test_at_least_explicit_asset_total_remains_bounded():
    data = spec().model_dump()
    data["pattern"] = {"kind": "line"}
    data["items"] = {"mode": "counts", "assets": [{"alias": "apple", "count": 1000},
                                                 {"alias": "banana", "count": 1}],
                     "requested_count": 5, "count_mode": "at_least"}
    with pytest.raises(ValueError, match="count_limit_exceeded"):
        plan_arrangement(ArrangementSpec.model_validate(data))


@pytest.mark.parametrize("kind", ["grid", "checker"])
@pytest.mark.parametrize("count", [5, 7])
def test_explicit_rectangular_exact_count_conflict_is_rejected(kind, count):
    data = spec().model_dump()
    data["pattern"] = {"kind": kind, "rows": 2, "cols": 3}
    data["items"]["requested_count"] = count
    with pytest.raises(ValidationError, match="scene_layout_count_conflict"):
        ArrangementSpec.model_validate(data)


def test_checker_count_only_keeps_exact_quantity_and_parity():
    data = spec().model_dump()
    data["pattern"] = {"kind": "checker"}
    data["items"] = {"mode": "sequence", "assets": [{"alias": "apple"}, {"alias": "banana"}],
                     "sequence": ["apple", "banana"], "requested_count": 5}
    value = ArrangementSpec.model_validate(data)
    from robot_agent_brain.planning.layout_planner import expanded_aliases
    assert expanded_aliases(value) == ["apple", "banana", "apple", "banana", "apple"]
    assert len(plan_arrangement(value).slots) == 5


def test_auto_spacing_cannot_silently_discard_explicit_distance():
    from robot_agent_brain.models.understanding_wire import encode, decode
    from jsonschema import ValidationError as WireError
    data = spec().model_dump(mode="json")
    data["spacing"] = {"mode": "auto", "auto": True, "value_m": .2}
    with pytest.raises(ValidationError, match="auto_value_conflict"):
        ArrangementSpec.model_validate(data)
    wire = encode({"status": "accepted", "turn_kind": "scene_layout", "arrangement_spec": data})
    with pytest.raises(WireError):
        decode(wire)


@pytest.mark.parametrize("value", [True, False, "4", 4.0, 4.5])
@pytest.mark.parametrize("field", ["requested_count", "count", "rows", "cols"])
def test_layout_counts_are_not_coerced(field, value):
    data = spec().model_dump()
    target = (data["pattern"] if field in {"rows", "cols"} else
              data["items"]["assets"][0] if field == "count" else data["items"])
    target[field] = value
    with pytest.raises(ValidationError):
        ArrangementSpec.model_validate(data)


@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_auto_count_authorization_is_a_boolean(value):
    data = spec().model_dump()
    data["items"].update(count_mode="auto", auto_count=value)
    with pytest.raises(ValidationError):
        ArrangementSpec.model_validate(data)


@pytest.mark.parametrize("kind,extra", [
    ("line", {"radius_m": .1}), ("alternating", {"text": "apple"}),
    ("grid", {"angle_span_deg": 180}), ("scatter", {"rows": 2}),
])
def test_pattern_rejects_inactive_nondefault_parameters(kind, extra):
    from robot_agent_brain.contracts.arrangement import ArrangementPattern
    with pytest.raises(ValidationError, match="pattern_field_forbidden"):
        ArrangementPattern.model_validate({"kind": kind, **extra})


def test_circle_has_no_world_coordinates():
    result = plan_arrangement(spec("circle", 1))
    assert result.slot_frame == "normalized_region_2d"
    assert result.slots[0].u == pytest.approx(.95)


def test_resolver_binds_only_matching_slot_count():
    arrangement = spec()
    plan = plan_arrangement(arrangement)
    resolved = LayoutResolver().resolve(arrangement, plan, scene_id=4, scene_version=2,
                                        instance_ids=[11, 12, 13, 14])
    assert resolved.slot_bindings == {"s0": 11, "s3": 14, "s2": 13, "s1": 12}
    with pytest.raises(ValueError, match="instance_count"):
        LayoutResolver().resolve(arrangement, plan, scene_id=4, scene_version=2,
                                 instance_ids=[11])


def test_resolver_projects_normalized_slots_without_scene_mutation():
    arrangement = spec()
    plan = plan_arrangement(arrangement)
    resolved = LayoutResolver().resolve(
        arrangement, plan, scene_id=4, scene_version=2,
        instance_ids=[11, 12, 13, 14],
        surface_bounds=((-1.0, -0.5), (1.0, 0.5)),
    )
    assert resolved.world_positions["s0"] == pytest.approx((-1.0, -0.5))
    assert resolved.world_positions["s3"] == pytest.approx((1.0, 0.5))

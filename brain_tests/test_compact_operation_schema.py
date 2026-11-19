from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from robot_agent_brain.contracts.turn import SceneEditIntent
from robot_agent_brain.contracts.scene_edit_rules import MOTION_ALLOWED
from robot_agent_brain.models.understanding_wire import compact_schema, decode, encode


def envelope(operation):
    return encode({"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
        "operations": [{"target": "apple", **operation}]}})


@pytest.mark.parametrize("field,value", [(key, value) for key in ("ax", "ad", "di", "dm", "ms", "cf", "po", "sx")
                                        for value in (None, 0, "z")])
def test_add_forbidden_presence_rejected_before_canonical(field, value):
    wire = envelope({"operation": "add"})
    wire["se"]["o"][0][field] = value
    original = deepcopy(wire)
    with pytest.raises(ValidationError):
        decode(wire)
    assert wire == original


@pytest.mark.parametrize("operation", [
    {"operation": "add"}, {"operation": "remove"},
    {"operation": "replace", "replacement_entity": "banana"},
    {"operation": "translate", "direction": "right", "distance_m": .005},
    {"operation": "translate", "direction": "right", "motion_scale": "small"},
    {"operation": "rotate", "axis": "z", "angle_deg": 0},
    {"operation": "orient", "posture": "upright"},
    {"operation": "move_relative", "relation": "near", "reference": "basket"},
    {"operation": "move_relative", "placement_goal": {"relation": "on", "reference": "table"}},
    {"operation": "update_properties", "properties": {"color": "blue"}},
    {"operation": "update", "relation": "on", "reference": "table", "placement_region": "left_front"},
    {"operation": "scale", "scale_mode": "multiply", "scale_xyz": [1.1, 1.1, 1.1]},
    {"operation": "scale", "scale_direction": "enlarge", "scale_amount": "small"},
])
def test_all_operations_lossless(operation):
    expanded = decode(envelope(operation))["scene_edit"]["operations"][0]
    expected = {"target": "apple", **operation}
    assert expanded == expected
    assert SceneEditIntent.model_validate(expanded) == SceneEditIntent.model_validate(expected)


@pytest.mark.parametrize("operation", [
    {"operation": "rotate", "axis": "z"},
    {"operation": "rotate", "axis": "z", "angle_deg": 90, "direction": "right"},
    {"operation": "remove", "placement_hint": "any"},
    {"operation": "replace"}, {"operation": "orient"},
    {"operation": "add", "relation": "on"},
    {"operation": "add", "reference": "table"},
    {"operation": "add", "relation": "near", "reference": "table", "placement_region": "left_front"},
    {"operation": "scale", "scale_mode": "multiply"},
    {"operation": "scale", "scale_mode": "multiply", "scale_xyz": [1, 1, 1], "scale_amount": "small"},
    {"operation": "translate", "direction": "right", "distance_m": .01, "motion_scale": "small"},
])
def test_illegal_combinations_not_repaired(operation):
    with pytest.raises(ValidationError):
        decode(envelope(operation))


def test_schema_operation_coverage_and_closed_branches():
    schema = compact_schema()
    Draft202012Validator.check_schema(schema)
    branches = schema["$defs"]["SceneEditIntent"]["anyOf"]
    assert {b["properties"]["op"]["const"] for b in branches} == set(MOTION_ALLOWED)
    for b in branches:
        assert b["additionalProperties"] is False
        assert list(b["properties"])[:2] == ["op", "t"]
        if b["properties"]["op"]["const"] == "add":
            assert not ({"ax", "ad"} & b["properties"].keys())


def test_full_legacy_normalizers_unchanged():
    assert SceneEditIntent(operation="add", target="apple", axis=None, angle_deg=None).axis is None
    assert SceneEditIntent(operation="remove", target="apple", placement_hint="any").placement_hint is None
    rotation = SceneEditIntent(operation="rotate", target="apple", axis="z", angle_deg=90, direction="right")
    assert rotation.angle_deg == -90 and rotation.direction is None
    assert SceneEditIntent(operation="add", target="apple", properties={"position_hint": "center"}).placement_hint == "center"

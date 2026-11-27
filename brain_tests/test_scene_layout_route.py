from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.contracts.turn import TurnKind
from robot_agent_brain.models.understanding_wire import encode, decode
import pytest
from jsonschema import ValidationError


def payload():
    return {
        "protocol_version": "task_understanding.v3.1", "status": "accepted", "turn_kind": "scene_layout",
        "arm_usage": "unspecified", "hold_constraints": [], "clarification_question": None,
        "scene_edit": None,
        "arrangement_spec": {
            "arrangement_id": "arr-apples", "operation": "create", "basis": "current",
            "pattern": {"kind": "grid", "rows": 1, "cols": 2},
            "items": {"mode": "single", "assets": [{"alias": "apple"}], "requested_count": 2, "count_mode": "exact"},
            "region": {"kind": "surface_region", "surface_ref": "table", "side": "center"},
            "spacing": {"mode": "center", "value_m": 0.05, "auto": False},
        },
        "scene_query": None, "session_control": None, "robot_setup_request": None,
        "robot_asset_switch": None, "initial_robot_asset": None, "robot_asset": None,
        "gripper_asset": None, "camera_asset": None, "profile_id": None,
        "entities": [], "operations": [], "relations": [],
    }


def test_compact_layout_requires_explicit_operation_even_create():
    compact = encode(payload())
    from robot_agent_brain.models.understanding_wire import FIELDS
    key = FIELDS["operation"]
    assert compact["at"][key] == "create"
    del compact["at"][key]
    with pytest.raises(ValidationError):
        decode(compact)


def test_scene_layout_wire_round_trips():
    turn = parse_qwen_turn(payload(), "排列两个苹果")
    assert turn.turn_kind == TurnKind.SCENE_LAYOUT
    assert turn.arrangement_spec.arrangement_id == "arr-apples"


def test_compact_layout_requires_basis_without_defaulting_to_current():
    compact = encode(payload())
    assert compact["at"].pop("bs") == "current"
    with pytest.raises(ValidationError):
        decode(compact)
    legacy = payload()
    del legacy["arrangement_spec"]["basis"]
    assert parse_qwen_turn(legacy, "排列两个苹果").arrangement_spec.basis == "current"


def test_scene_layout_compact_round_trip():
    value = payload()
    compact = encode(value)
    assert compact["k"] == "scene_layout"
    assert "at" in compact
    restored = decode(compact)
    assert restored["turn_kind"] == "scene_layout"
    assert restored["arrangement_spec"]["arrangement_id"] == "arr-apples"


@pytest.mark.parametrize("region", [
    {"sv": "table", "ah": "basket", "yd": "right_half"},
    {"ki": "surface_region", "sv": "table", "ah": "basket", "yd": "right_half"},
    {"ki": "relative", "sv": "table", "yd": "right_half"},
    {"ki": "relative", "sv": "table", "ah": "basket"},
    {"ki": "relative", "sv": "table", "ah": "basket", "yd": "center"},
])
def test_compact_region_cannot_silently_ignore_anchor(region):
    compact = encode(payload())
    compact["at"]["re"] = region
    with pytest.raises(ValidationError):
        decode(compact)


def test_full_region_cannot_silently_ignore_anchor():
    from robot_agent_brain.contracts.arrangement import ArrangementRegion
    with pytest.raises(ValueError, match="scene_layout_anchor_forbidden"):
        ArrangementRegion(surface_ref="table", anchor_ref="basket", side="right_half")


def test_compact_relative_region_preserves_explicit_anchor_and_direction():
    value = payload()
    value["arrangement_spec"]["region"] = {
        "kind": "relative", "surface_ref": "table", "anchor_ref": "basket", "side": "right_half"}
    assert decode(encode(value))["arrangement_spec"]["region"] == value["arrangement_spec"]["region"]


@pytest.mark.parametrize("spacing", [{}, {"ao": True}, {"mo": "auto"},
                                    {"mo": "center", "vm": None},
                                    {"mo": "edge", "vm": .1, "ao": True}])
def test_layout_compact_schema_refuses_incomplete_or_conflicting_spacing(spacing):
    compact = encode(payload())
    compact["at"]["sp"] = spacing
    with pytest.raises(ValidationError):
        decode(compact)


def test_layout_compact_sequence_requires_mode_and_sequence():
    compact = encode(payload())
    assert compact["at"]["it"]["mo"] == "single"
    compact["at"]["it"]["mo"] = "sequence"
    with pytest.raises(ValidationError):
        decode(compact)


@pytest.mark.parametrize("value", [None, .2])
def test_layout_compact_grid_cannot_carry_radius_even_null(value):
    compact = encode(payload())
    compact["at"]["pn"]["rm"] = value
    with pytest.raises(ValidationError):
        decode(compact)

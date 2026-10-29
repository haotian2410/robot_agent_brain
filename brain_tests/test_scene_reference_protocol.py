"""P0 regression fixtures for environment references in scene edits."""

import json

from robot_agent_brain.models.task_understanding import parse_qwen_turn


def _scene_edit_payload(*, reference="table", name="table"):
    return {
        "status": "accepted",
        "turn_kind": "scene_edit",
        "arm_usage": "unspecified",
        "hold_constraints": [],
        "clarification_question": None,
        "scene_edit": {
            "scene_basis": "current",
            "entities": [
                {"entity_id": "basket", "semantic_name": "basket", "category": "container"},
                {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
                {"entity_id": "banana", "semantic_name": "banana", "category": "fruit"},
            ],
            "relations": [],
            "operations": [
                {"operation": "add", "target": "basket", "relation": "on", "reference": reference},
                {"operation": "add", "target": "apple", "relation": "on", "reference": reference},
                {"operation": "add", "target": "banana", "relation": "on", "reference": reference},
            ],
        },
        "scene_query": None,
        "session_control": None,
        "robot_setup_request": None,
        "entities": [],
        "operations": [],
        "relations": [],
    }


def test_qwen_scene_edit_can_reference_existing_table_without_entity_selector():
    """Reproduces the live failure before AABB/layout validation is reached."""
    turn = parse_qwen_turn(_scene_edit_payload(), "在桌面上放置篮子、苹果和香蕉")
    assert turn.scene_edit is not None
    assert [operation.reference for operation in turn.scene_edit.operations] == ["table"] * 3


def test_fixture_is_wire_json():
    """Keep the reproduction compatible with the exact provider response shape."""
    json.dumps(_scene_edit_payload(), ensure_ascii=False)

"""P0 regression fixtures for environment references in scene edits."""

import json

from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.grounding.scene_reference_resolver import SceneReferenceResolver
from component_fixtures import demo_bootstrap


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


def test_scene_reference_alias_resolves_to_existing_default_surface():
    config = BrainConfig()
    _, bootstrapper = demo_bootstrap(config)
    scene = bootstrapper.prepare(parse_qwen_turn(_scene_edit_payload(), "在桌面上放置篮子、苹果和香蕉"), scene_id=1).scene
    resolved = SceneReferenceResolver(table_metadata_ref="$DEMO_LIBRARY/1").resolve(
        "台面", entities=[], scene=scene, default_surface_id=0)
    assert resolved.canonical_id == "table"
    assert resolved.scope == "scene_ref"
    assert resolved.object_id == 0


def test_unknown_scene_reference_is_not_guessed():
    config = BrainConfig()
    _, bootstrapper = demo_bootstrap(config)
    scene = bootstrapper.prepare(parse_qwen_turn(_scene_edit_payload(), "在桌面上放置篮子、苹果和香蕉"), scene_id=1).scene
    try:
        SceneReferenceResolver().resolve("window", entities=[], scene=scene, default_surface_id=0)
    except Exception as exc:
        assert "scene_reference_unresolved" in str(exc)
    else:
        raise AssertionError("unknown reference was guessed")


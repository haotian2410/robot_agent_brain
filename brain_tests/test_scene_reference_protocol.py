"""P0 regression fixtures for environment references in scene edits."""

import json

from robot_agent_brain.models.task_understanding import parse_qwen_turn
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.grounding.scene_reference_resolver import SceneReferenceResolver
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.grounding.scene_object_selector import SceneObjectSelector
from robot_agent_brain.contracts.spatial import SpatialRelation
from robot_agent_brain.contracts.task_intent import TaskEntity
from test_query_scene_continuity import supported_scene
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


def test_three_add_operations_using_table_reference_produce_one_scene_patch():
    config = BrainConfig()
    assets, bootstrapper = demo_bootstrap(config)
    turn = parse_qwen_turn(_scene_edit_payload(), "在桌面上放置篮子、苹果和香蕉")
    initial = bootstrapper.prepare(turn, scene_id=1)
    result = SceneEditor(assets, table_metadata_ref="$DEMO_LIBRARY/1").edit_result(
        turn.scene_edit, initial.scene, defaults=config.load_defaults())
    final = SceneManager(initial.scene).apply_patch(result.patch)
    names = [obj.object_name_in_scene for obj in final.objects]
    assert names.count("basket") == 1
    assert names.count("apple") == 1
    assert names.count("banana") == 1
    assert len(result.patch.operations) == 6  # add + Semantic for each object


def test_bootstrap_resolves_environment_table_without_precreating_add_targets():
    config = BrainConfig()
    _, bootstrapper = demo_bootstrap(config)
    turn = parse_qwen_turn(_scene_edit_payload(), "在桌面上放置篮子、苹果和香蕉")
    result = bootstrapper.prepare(turn, scene_id=1)
    names = [component.properties.get("semantic_name")
             for obj in result.scene.objects
             for component in obj.components if component.component_type == "Semantic"]
    assert names == ["table"]
    assert result.asset_bindings == {}


def test_selection_relation_can_use_environment_table_reference():
    scene = supported_scene()
    entities = [TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")]
    relations = [SpatialRelation(subject="apple", relation="left_of", reference="table")]
    selected = SceneObjectSelector(assets=BrainConfig().load_assets()).resolve(
        "apple", entities, relations, scene
    )
    assert [obj.object_id_in_scene for obj in selected] == [1]

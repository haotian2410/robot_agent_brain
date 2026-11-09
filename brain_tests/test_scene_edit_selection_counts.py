from types import SimpleNamespace

import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.spatial import SpatialRelation
from robot_agent_brain.contracts.task_intent import QuantityMode, TaskEntity
from robot_agent_brain.contracts.turn import SceneEditPlan
from robot_agent_brain.grounding.scene_object_selector import SceneObjectSelector
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.models.qwen_http import (
    _repair_live_explicit_instance_delete,
    _repair_live_scene_edit_quantity,
)
from robot_agent_brain.models.task_understanding import parse_qwen_turn
from test_query_scene_continuity import supported_scene


def scene_with_apples():
    scene = supported_scene()
    for object_id, x, y in ((3, -0.3, 0.3), (4, 0.2, -0.3), (5, 0.3, 0.3)):
        apple = scene.objects[1].model_copy(deep=True)
        apple.object_id_in_scene = object_id
        next(component for component in apple.components if component.component_type == "Transform").properties[
            "position"
        ] = [x, y, 0.045]
        scene.objects.append(apple)
    return scene


def apples(*, count=1, mode=QuantityMode.SINGLE, all_available=False, ids=None, subset=False):
    return TaskEntity(entity_id="target", semantic_name="apple", category="fruit",
                      count=count, quantity_mode=mode, all_available=all_available,
                      scene_object_ids=ids or [], select_count_from_candidates=subset)


def test_single_target_still_requires_clarification_with_multiple_matches():
    scene = scene_with_apples()
    with pytest.raises(ValueError, match="grounding_ambiguous"):
        SceneObjectSelector(assets=BrainConfig().load_assets()).resolve(
            "target", [apples()], [], scene, allow_partial=True
        )


def test_explicit_count_selects_stable_subset_after_direction_filter():
    scene = scene_with_apples()
    selected = SceneObjectSelector(assets=BrainConfig().load_assets()).resolve(
        "target", [apples(count=2, mode=QuantityMode.ALL, subset=True)],
        [SpatialRelation(subject="target", relation="left")], scene,
        allow_partial=True,
    )
    assert [item.object_id_in_scene for item in selected] == [1, 3]


def test_all_available_remove_and_color_update_cover_every_match():
    scene = scene_with_apples()
    editor = SceneEditor(BrainConfig().load_assets())
    remove = SceneEditPlan(
        entities=[apples(mode=QuantityMode.ALL, all_available=True)],
        operations=[{"operation": "remove", "target": "target"}],
    )
    result = editor.edit_result(remove, scene)
    assert result.deleted_object_ids == [1, 3, 4, 5]

    color = SceneEditPlan(
        entities=[apples(mode=QuantityMode.ALL, all_available=True)],
        operations=[{"operation": "update_properties", "target": "target",
                     "properties": {"color": "blue"}}],
    )
    result = editor.edit_result(color, scene)
    updated = SceneManager(scene).apply_patch(result.patch)
    for object_id in (1, 3, 4, 5):
        assert SceneIndex(updated).component(object_id, "MeshRenderer").properties[
            "forceOverrideColor"] == "#0000FF"

    replace = SceneEditPlan(
        entities=[apples(mode=QuantityMode.ALL, all_available=True),
                  TaskEntity(entity_id="replacement", semantic_name="banana", category="fruit")],
        operations=[{"operation": "replace", "target": "target",
                     "replacement_entity": "replacement"}],
    )
    result = editor.edit_result(replace, scene, next_scene_object_id=10)
    assert result.deleted_object_ids == [1, 3, 4, 5]
    assert result.created_object_ids == [10, 11, 12, 13]


def test_explicit_count_can_be_replaced_even_when_replacement_count_is_one():
    scene = scene_with_apples()
    plan = SceneEditPlan(
        entities=[apples(count=2, mode=QuantityMode.ALL, subset=True),
                  TaskEntity(entity_id="replacement", semantic_name="banana", category="fruit")],
        operations=[{"operation": "replace", "target": "target",
                     "replacement_entity": "replacement"}],
    )
    result = SceneEditor(BrainConfig().load_assets()).edit_result(
        plan, scene, next_scene_object_id=10
    )
    assert result.deleted_object_ids == [1, 3]
    assert result.created_object_ids == [10, 11]


def test_explicit_count_removal_and_color_change_use_the_same_subset():
    scene = scene_with_apples()
    editor = SceneEditor(BrainConfig().load_assets())
    plan = SceneEditPlan(
        entities=[apples(count=2, mode=QuantityMode.ALL, subset=True)],
        operations=[{"operation": "remove", "target": "target"}],
    )
    result = editor.edit_result(plan, scene)
    assert result.deleted_object_ids == [1, 3]

    color = SceneEditPlan(
        entities=[apples(count=2, mode=QuantityMode.ALL, subset=True)],
        operations=[{"operation": "update_properties", "target": "target",
                     "properties": {"color": "blue"}}],
    )
    updated = SceneManager(scene).apply_patch(editor.edit_result(color, scene).patch)
    for object_id in (1, 3):
        assert SceneIndex(updated).component(object_id, "MeshRenderer").properties[
            "forceOverrideColor"] == "#0000FF"
    for object_id in (4, 5):
        assert SceneIndex(updated).component(object_id, "MeshRenderer") is None


def test_count_without_explicit_subset_intent_does_not_pick_first_matches():
    scene = scene_with_apples()
    plan = SceneEditPlan(
        entities=[apples(count=2, mode=QuantityMode.ALL)],
        operations=[{"operation": "remove", "target": "target"}],
    )
    with pytest.raises(ValueError, match="grounding_ambiguous"):
        SceneEditor(BrainConfig().load_assets()).edit_result(plan, scene)


@pytest.mark.parametrize("operation,relation,expected_id", [
    ({"operation": "remove", "target": "target"}, "rightmost", 5),
    ({"operation": "replace", "target": "target", "replacement_entity": "replacement"},
     "leftmost", 3),
    ({"operation": "update_properties", "target": "target",
      "properties": {"color": "yellow"}}, "leftmost", 3),
])
def test_extreme_selector_applies_to_scene_modifications(operation, relation, expected_id):
    scene = scene_with_apples()
    entities = [apples()]
    if operation["operation"] == "replace":
        entities.append(TaskEntity(entity_id="replacement", semantic_name="banana", category="fruit"))
    plan = SceneEditPlan(entities=entities,
                         relations=[SpatialRelation(subject="target", relation=relation)],
                         operations=[operation])
    result = SceneEditor(BrainConfig().load_assets()).edit_result(plan, scene)
    if operation["operation"] == "remove":
        assert result.deleted_object_ids == [expected_id]
    elif operation["operation"] == "replace":
        assert result.deleted_object_ids == [expected_id]
        assert result.created_object_ids == [6]
    else:
        updated = SceneManager(scene).apply_patch(result.patch)
        assert SceneIndex(updated).component(expected_id, "MeshRenderer").properties[
            "forceOverrideColor"] == "#FFFF00"
        assert SceneIndex(updated).component(1, "MeshRenderer") is None


def test_explicit_scene_object_id_filters_semantic_candidates():
    scene = scene_with_apples()
    selected = SceneObjectSelector(assets=BrainConfig().load_assets()).resolve(
        "target", [apples(ids=[4])], [], scene
    )
    assert [item.object_id_in_scene for item in selected] == [4]

    with pytest.raises(ValueError, match="grounding_binding_invalid"):
        SceneObjectSelector(assets=BrainConfig().load_assets()).resolve(
            "target", [apples(ids=[2])], [], scene
        )


def test_explicit_instance_delete_can_recover_a_clarification():
    clarification = {"status": "clarification_required", "turn_kind": "unsupported_task",
                     "clarification_question": "Which object does id 4 refer to?"}
    instruction = "Delete the apple with object id 4"
    scene_context = {"objects": [{"object_id": 4, "semantic_name": "apple", "category": "fruit"}]}
    repaired = _repair_live_explicit_instance_delete(
        clarification, instruction, scene_context, catalog=None
    )
    turn = parse_qwen_turn(repaired, instruction)
    assert turn.scene_edit.entities[0].scene_object_ids == [4]
    assert turn.scene_edit.operations[0].operation == "remove"


def test_explicit_multiple_instance_ids_are_deleted_as_a_set():
    clarification = {"status": "clarification_required", "turn_kind": "unsupported_task",
                     "clarification_question": "Are these object ids or asset ids?"}
    instruction = "Delete id为18 19 20 的魔方"
    scene_context = {"objects": [{"object_id": object_id, "semantic_name": "rubiks_cube",
                                  "category": "object"}
                     for object_id in (18, 19, 20)]}
    catalog = SimpleNamespace(models=[SimpleNamespace(
        asset_key="model:1", name="rubiks_cube", aliases=["魔方"], category="object"
    )])
    repaired = _repair_live_explicit_instance_delete(
        clarification, instruction, scene_context, catalog=catalog
    )
    turn = parse_qwen_turn(repaired, instruction)
    assert turn.scene_edit.entities[0].scene_object_ids == [18, 19, 20]

    scene = supported_scene()
    for object_id in (18, 19, 20):
        cube = scene.objects[1].model_copy(deep=True)
        cube.object_id_in_scene = object_id
        next(component for component in cube.components if component.component_type == "Transform").properties[
            "position"
        ] = [0, (object_id - 19) * .2, .045]
        next(component for component in cube.components if component.component_type == "Semantic").properties[
            "semantic_name"
        ] = "rubiks_cube"
        next(component for component in cube.components if component.component_type == "Semantic").properties[
            "category"
        ] = "object"
        scene.objects.append(cube)
    result = SceneEditor(BrainConfig().load_assets()).edit_result(turn.scene_edit, scene)
    assert result.deleted_object_ids == [18, 19, 20]


@pytest.mark.parametrize("instruction,expected_count,all_available", [
    ("删除三个魔方", 3, False),
    ("删除其中两个魔方", 2, False),
    ("Delete three rubiks_cube objects", 3, False),
    ("Delete two of the rubiks_cube objects", 2, False),
    ("把所有魔方改成蓝色", 1, True),
])
def test_live_edit_quantity_repair_preserves_explicit_scope(instruction, expected_count, all_available):
    catalog = SimpleNamespace(models=[SimpleNamespace(
        asset_key="model:1", name="rubiks_cube", aliases=["魔方"], category="object"
    )])
    value = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "cubes", "semantic_name": "rubiks_cube", "category": "object",
                      "count": 3, "quantity_mode": "candidate_pool", "all_available": False}],
        "operations": [{"operation": "remove", "target": "cubes"}],
    }}
    repaired = _repair_live_scene_edit_quantity(value, instruction, catalog)
    entity = repaired["scene_edit"]["entities"][0]
    assert entity["quantity_mode"] == "all"
    assert entity["all_available"] is all_available
    assert entity["count"] == expected_count


def test_live_edit_count_is_applied_after_direction_filter():
    catalog = SimpleNamespace(models=[SimpleNamespace(
        asset_key="model:1", name="rubiks_cube", aliases=["魔方"], category="object"
    )])
    value = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "cubes", "semantic_name": "rubiks_cube", "category": "object",
                      "count": 3, "quantity_mode": "candidate_pool"}],
        "relations": [{"scope": "selection", "subject": "cubes", "relation": "left"}],
        "operations": [{"operation": "remove", "target": "cubes"}],
    }}
    repaired = _repair_live_scene_edit_quantity(value, "删除左边三个魔方", catalog)
    entity = repaired["scene_edit"]["entities"][0]
    assert entity["quantity_mode"] == "all"
    assert entity["count"] == 3


def test_live_candidate_pool_extreme_remains_a_single_result_selector():
    catalog = SimpleNamespace(models=[SimpleNamespace(
        asset_key="model:1", name="rubiks_cube", aliases=["魔方"], category="object"
    )])
    value = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "cubes", "semantic_name": "rubiks_cube", "category": "object",
                      "count": 3, "quantity_mode": "candidate_pool"}],
        "relations": [{"scope": "selection", "subject": "cubes", "relation": "rightmost"}],
        "operations": [{"operation": "remove", "target": "cubes"}],
    }}
    repaired = _repair_live_scene_edit_quantity(value, "删除两个魔方中最右边的那个", catalog)
    assert repaired["scene_edit"]["entities"][0]["quantity_mode"] == "candidate_pool"


def test_unspecified_single_does_not_turn_into_an_arbitrary_first_match():
    catalog = SimpleNamespace(models=[SimpleNamespace(
        asset_key="model:1", name="rubiks_cube", aliases=["魔方"], category="object"
    )])
    value = {"status": "accepted", "turn_kind": "scene_edit", "scene_edit": {
        "entities": [{"entity_id": "cube", "semantic_name": "rubiks_cube", "category": "object",
                      "count": 1, "quantity_mode": "all", "all_available": False}],
        "relations": [],
        "operations": [{"operation": "remove", "target": "cube"}],
    }}
    repaired = _repair_live_scene_edit_quantity(value, "Delete a rubiks_cube", catalog)
    assert repaired["scene_edit"]["entities"][0]["quantity_mode"] == "single"


def test_explicit_instance_delete_does_not_cross_match_another_semantic():
    clarification = {"status": "clarification_required", "turn_kind": "unsupported_task",
                     "clarification_question": "Which object does id 4 refer to?"}
    repaired = _repair_live_explicit_instance_delete(
        clarification, "Delete the apple with object id 4",
        {"objects": [{"object_id": 4, "semantic_name": "banana", "category": "fruit"}]},
        catalog=None,
    )
    assert repaired is clarification

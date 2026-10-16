import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneComponent
from robot_agent_brain.contracts.turn import SceneEditPlan
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.scene_graph import world_transform
from test_query_scene_continuity import supported_scene


def plan(operations=None):
    return SceneEditPlan(entities=[{"entity_id": "old", "semantic_name": "apple", "category": "fruit"},
                                  {"entity_id": "new", "semantic_name": "banana", "category": "fruit"}],
                         operations=operations or [{"operation": "replace", "target": "old", "replacement_entity": "new"}])


def test_replace_new_id_asset_height_and_no_inherited_override():
    scene = supported_scene()
    scene.objects[1].components.append(SceneComponent(component_type="MeshRenderer", properties={"forceOverrideColor": "#0000FF"}))
    scene.objects[1].components.append(SceneComponent(component_type="OldAssetPrivate", properties={"value": 7}))
    original = scene.model_dump()
    editor = SceneEditor(BrainConfig().load_assets())
    result = editor.edit_result(plan(), scene, next_scene_object_id=20)
    updated = SceneManager(scene, next_scene_object_id=20).apply_patch(result.patch)
    assert scene.model_dump() == original
    assert result.deleted_object_ids == [1] and result.created_object_ids == [20]
    index = SceneIndex(updated)
    assert index.metadata_ref(20) == "$DEMO_LIBRARY/3"
    assert index.semantic(20).support == 0
    assert index.transform(20).scale == (1., 1., 1.)
    assert world_transform(updated, 20).position == pytest.approx((-.25, 0, .025))
    assert index.component(20, "MeshRenderer") is None and index.component(20, "OldAssetPrivate") is None
    assert updated.scene_version == scene.scene_version + 1


def test_mixed_replace_and_translate_uses_new_binding():
    scene = supported_scene()
    edits = plan([{"operation": "replace", "target": "old", "replacement_entity": "new"},
                  {"operation": "translate", "target": "new", "direction": "right", "distance_m": .05}])
    result = SceneEditor(BrainConfig().load_assets()).edit_result(edits, scene, next_scene_object_id=20)
    updated = SceneManager(scene, next_scene_object_id=20).apply_patch(result.patch)
    assert world_transform(updated, 20).position[0] == pytest.approx(-.2)
    assert world_transform(updated, 2).position[0] == .25  # existing banana untouched
    assert updated.scene_version == 1


def test_replacing_parent_is_rejected_without_mutation():
    scene = supported_scene()
    SceneIndex(scene).component(2, "Transform").properties["parent"] = 1
    before = scene.model_dump()
    with pytest.raises(ValueError, match="dependent_object"):
        SceneEditor(BrainConfig().load_assets()).edit_result(plan(), scene)
    assert scene.model_dump() == before


def test_followup_failure_rolls_back_entire_replacement():
    scene = supported_scene()
    before = scene.model_dump()
    edits = plan([{"operation": "replace", "target": "old", "replacement_entity": "new"},
                  {"operation": "translate", "target": "new", "direction": "right", "distance_m": .5}])
    with pytest.raises(ValueError, match="collision"):
        SceneEditor(BrainConfig().load_assets()).edit_result(edits, scene)
    assert scene.model_dump() == before

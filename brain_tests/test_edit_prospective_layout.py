import pytest
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.turn import SceneEditIntent, SceneEditPlan
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager


def fixture():
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1,.1,.1)),
                               ModelProperty(asset_id="box", semantic_name="box", category="container", dimensions_m=(.2,.2,.2))])
    scene = SceneConfig(scene_id="s", objects=[
        SceneObject(scene_object_id="a1", semantic_name="apple", category="fruit", asset_id="apple"),
        SceneObject(scene_object_id="a2", semantic_name="apple", category="fruit", asset_id="apple", transform=Transform(position=(.2,0,0))),
        SceneObject(scene_object_id="b", semantic_name="box", category="container", asset_id="box", transform=Transform(position=(2,0,0)))])
    return SceneEditor(assets), scene


def test_collection_new_poses_are_checked_against_each_other():
    editor, scene = fixture()
    original = scene.model_dump()
    edit = SceneEditIntent(operation="move_relative", semantic_name="apple", category="fruit", count=2,
                           reference="b", relation="right_of")
    with pytest.raises(ValueError, match="scene_edit_transform_collision"):
        editor.edit(edit, scene)
    assert scene.model_dump() == original


def test_collection_translation_may_use_vacated_space():
    editor, scene = fixture()
    patch = editor.edit(SceneEditIntent(operation="translate", semantic_name="apple", category="fruit", count=2,
                                        direction="right", distance_m=.2), scene)
    result = SceneManager(scene).apply_patch(patch)
    assert [o.transform.position[0] for o in result.objects[:2]] == pytest.approx([.2,.4])
    assert result.scene_version == 1


def test_late_plan_failure_keeps_original_scene():
    editor, scene = fixture()
    original = scene.model_dump()
    plan = SceneEditPlan(operations=[
        SceneEditIntent(operation="translate", semantic_name="apple", category="fruit", count=2, direction="right", distance_m=.2),
        SceneEditIntent(operation="translate", semantic_name="missing", category="fruit", direction="right", distance_m=.2)])
    with pytest.raises(ValueError, match="scene_edit_object_missing"):
        editor.edit(plan, scene)
    assert scene.model_dump() == original

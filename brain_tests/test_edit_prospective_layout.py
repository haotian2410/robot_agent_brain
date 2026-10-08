import pytest
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.turn import SceneEditIntent, SceneEditPlan
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.scene.scene_graph import world_transform
from test_component_runtime import object_


def fixture():
    assets = BrainConfig().load_assets()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=[
        object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2"),
        object_(1, "apple", position=(.2,0,0), metadata_ref="$DEMO_LIBRARY/2"),
        object_(2, "box", "container", position=(2,0,0), metadata_ref="$DEMO_LIBRARY/5")])
    return SceneEditor(assets), scene


def test_collection_new_poses_are_checked_against_each_other():
    editor, scene = fixture()
    original = scene.model_dump()
    edit = SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=2, quantity_mode='all'), dict(entity_id="reference", semantic_name='box', category="container")], operations=[SceneEditIntent(operation='move_relative', relation='right_of', target="target", reference="reference")])
    with pytest.raises(ValueError, match="scene_edit_transform_collision"):
        editor.edit(edit, scene)
    assert scene.model_dump() == original


def test_collection_translation_may_use_vacated_space():
    editor, scene = fixture()
    patch = editor.edit(SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=2, quantity_mode='all')], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.2, target="target")]), scene)
    result = SceneManager(scene).apply_patch(patch)
    assert [world_transform(result, o.object_id_in_scene).position[0] for o in result.objects[:2]] == pytest.approx([.2,.4])
    assert result.scene_version == 1


def test_late_plan_failure_keeps_original_scene():
    editor, scene = fixture()
    original = scene.model_dump()
    plan = SceneEditPlan(entities=[
        dict(entity_id="apples", semantic_name="apple", category="fruit", count=2, quantity_mode="all"),
        dict(entity_id="missing", semantic_name="missing", category="fruit")], operations=[
        SceneEditIntent(operation="translate", target="apples", direction="right", distance_m=.2),
        SceneEditIntent(operation="translate", target="missing", direction="right", distance_m=.2)])
    with pytest.raises(ValueError, match="grounding_missing"):
        editor.edit(plan, scene)
    assert scene.model_dump() == original

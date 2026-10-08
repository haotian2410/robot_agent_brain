import math
from pathlib import Path

import pytest

from robot_agent_brain.config import LayoutDefaults
from robot_agent_brain.contracts.scene import SceneComponent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.contracts.turn import SceneEditPlan, SceneEditIntent
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_graph import world_transform
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from test_component_runtime import scene_, entity_
from test_component_bootstrap import FixtureLibrary, configured, turn


class UnavailableGeometry:
    def resolve(self, reference):
        raise LookupError("asset_missing")


def test_user_fixture_edit_preserves_light_camera_driver_and_metadata():
    codec = SceneFileCodec()
    scene = codec.load(Path(__file__).parent / "fixtures/shared_scene_v1.json")
    before = codec.payload(scene)
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="cube", semantic_name="cube", category="object")],
        operations=[SceneEditIntent(operation="translate", target="cube", direction="right", distance_m=.1)])
    changed = SceneManager(scene).apply_patch(SceneEditor(UnavailableGeometry()).edit(plan, scene))
    after = codec.payload(changed)
    assert after["objects"][1:] == before["objects"][1:]
    assert SceneIndex(changed).metadata_ref(0) == "$LIBRARY_SERVER/<id>"
    assert SceneIndex(changed).transform(1).parent == SceneIndex(changed).transform(2).parent == 0
    assert SceneIndex(changed).robot_driver(3) == SceneIndex(scene).robot_driver(3)
    assert after["scene_version"] == before["scene_version"] + 1


def test_parented_world_move_preserves_components_and_local_parent():
    scene = scene_()
    scene.objects[2].components.append(SceneComponent(component_type="Sensor", properties={"opaque": [1, None]}))
    before = scene.model_dump()
    plan = SceneEditPlan(entities=[entity_(exclude_scene_object_ids=[12])],
        operations=[SceneEditIntent(operation="translate", target="apple", direction="front", distance_m=.2)])
    patch = SceneEditor(UnavailableGeometry()).edit(plan, scene)
    changed = SceneManager(scene).apply_patch(patch)
    index = SceneIndex(changed)
    assert index.transform(11).parent == 8
    assert index.transform(11).position == pytest.approx((-9, .1, 0))
    assert world_transform(changed, 11).position == pytest.approx((1, .2, 0))
    assert index.semantic(11).support is None
    assert index.metadata_ref(11) == "$LIBRARY_SERVER/1"
    assert index.component(11, "Sensor").properties == {"opaque": [1, None]}
    assert changed.objects[:2] == scene.objects[:2]
    assert changed.objects[3] == scene.objects[3]
    assert scene.model_dump() == before


def test_object_local_move_uses_normalized_world_axis_not_parent_scale():
    scene = scene_()
    scene.objects[1].components[0].properties["quaternion_xyzw"] = [0, 0, math.sqrt(.5), math.sqrt(.5)]
    before = world_transform(scene, 11)
    plan = SceneEditPlan(entities=[entity_(exclude_scene_object_ids=[12])],
        operations=[SceneEditIntent(operation="translate", target="apple", direction="front",
                                    distance_m=.2, coordinate_frame="object_local")])
    changed = SceneManager(scene).apply_patch(SceneEditor(UnavailableGeometry()).edit(plan, scene))
    after = world_transform(changed, 11)
    assert after.position == pytest.approx((before.position[0] - .2, before.position[1], before.position[2]))


def test_new_ids_start_after_history_and_support_is_component_fact():
    library = FixtureLibrary()
    scene = configured(library).prepare(turn(), scene_id=0).scene
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="new", semantic_name="screwdriver", category="tool")],
        operations=[SceneEditIntent(operation="add", target="new")])
    editor = SceneEditor(library)
    result = editor.edit_result(plan, scene, defaults=LayoutDefaults(),
        seen_scene_object_ids={0, 1, 2, 3, 40}, next_scene_object_id=41)
    assert result.created_object_ids == [41]
    changed = SceneManager(scene, seen_scene_object_ids={0, 1, 2, 3, 40}, next_scene_object_id=41).apply_patch(result.patch)
    assert SceneIndex(changed).semantic(41).support == 0
    assert "retired_object_ids" not in changed.model_dump()
    assert result.entity_bindings == {"new": [41]}
    assert changed.scene_version == 2


def test_add_then_move_local_binding_is_one_atomic_version():
    library = FixtureLibrary()
    scene = configured(library).prepare(turn(), scene_id=0).scene
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="new", semantic_name="screwdriver", category="tool")],
        operations=[SceneEditIntent(operation="add", target="new"),
                    SceneEditIntent(operation="translate", target="new", direction="up", distance_m=.2)])
    result = SceneEditor(library).edit_result(plan, scene, defaults=LayoutDefaults())
    changed = SceneManager(scene).apply_patch(result.patch)
    assert changed.scene_version == scene.scene_version + 1
    assert result.created_object_ids == [4]
    assert SceneIndex(changed).semantic(4).support is None
    assert SceneIndex(changed).transform(4).position[2] > .2


def test_later_failure_never_changes_input_scene_or_allocates_id():
    library = FixtureLibrary()
    scene = configured(library).prepare(turn(), scene_id=0).scene
    before = scene.model_dump()
    plan = SceneEditPlan(entities=[TaskEntity(entity_id="new", semantic_name="screwdriver", category="tool")],
        operations=[SceneEditIntent(operation="add", target="new"),
                    SceneEditIntent(operation="update_properties", target="new", properties={"color": "red"})])
    with pytest.raises(ValueError, match="properties_unsupported"):
        SceneEditor(library).edit_result(plan, scene, defaults=LayoutDefaults())
    assert scene.model_dump() == before


def test_group_translation_checks_prospective_not_vacated_positions():
    library = FixtureLibrary()
    scene = configured(library).prepare(turn(), scene_id=0).scene
    plan = SceneEditPlan(entities=turn().task_intent.entities,
        operations=[SceneEditIntent(operation="translate", target="tools", direction="up", distance_m=.2)])
    changed = SceneManager(scene).apply_patch(SceneEditor(library).edit(plan, scene))
    for identifier in (2, 3):
        assert world_transform(changed, identifier).position[2] == pytest.approx(
            world_transform(scene, identifier).position[2] + .2)
        assert SceneIndex(changed).semantic(identifier).support is None

import pytest

from robot_agent_brain.contracts.scene import SceneComponent, SceneObject
from robot_agent_brain.scene.id_remapper import remap_scene
from test_robot_profiles_state import fixture


def test_restore_remaps_all_ids_and_known_refs_without_changing_source():
    _, scene, setup = fixture()
    # Apple is parented to robot 2 and supported by robot 3 for this structural
    # test only; no geometry/physical support assertion is made.
    apple = scene.objects[-1]
    for c in apple.components:
        if c.component_type == "Transform":
            c.properties["parent"] = 2
        if c.component_type == "Semantic":
            c.properties["support"] = 3
    scene.objects.append(SceneObject(object_id_in_scene=8, object_name_in_scene="wrist", components=[
        SceneComponent(component_type="Transform", properties={"parent": 2, "scale": [1, 1, 1]}),
        SceneComponent(component_type="RobotAttachment", properties={"parent_object_id": 2, "parent_joint": "joint1",
            "parent_link": "link1", "child_link": "camera", "connection_type": "fixed",
            "transform": {"position": [0, 0, 0], "quaternion_xyzw": [0, 0, 0, 1], "reference_frame": "parent_link"}})]))
    before = scene.model_dump()
    result = remap_scene(scene, new_scene_id=22, next_object_id=100, robot_setup=setup)
    assert result.id_map == {2: 100, 3: 101, 7: 102, 8: 103}
    assert result.next_scene_object_id == 104
    assert result.scene.scene_version == 1 and result.scene.scene_id == 22
    assert result.robot_setup.arms["left"].robot_object_id == 100
    from robot_agent_brain.scene.component_access import SceneIndex
    index = SceneIndex(result.scene)
    assert index.transform(102).parent == 100
    assert index.semantic(102).support == 101
    assert index.properties(103, "RobotAttachment").parent_object_id == 100
    assert scene.model_dump() == before
    assert setup.arms["left"].robot_object_id == 2


def test_unknown_component_is_not_guessed_or_silently_copied():
    _, scene, _ = fixture()
    scene.objects[-1].components.append(SceneComponent(component_type="VendorLink", properties={"target": 2}))
    with pytest.raises(ValueError, match="remap_rule_missing"):
        remap_scene(scene, new_scene_id=22, next_object_id=100)


@pytest.mark.parametrize("start", [True, -1, 2**53])
def test_allocator_invalid_or_exhausted(start):
    _, scene, _ = fixture()
    with pytest.raises(ValueError):
        remap_scene(scene, new_scene_id=22, next_object_id=start)

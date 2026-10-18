import pytest

from robot_agent_brain.contracts.scene import SceneComponent
from robot_agent_brain.scene.id_remapper import remap_scene
from robot_agent_brain.scene.robot_setup_manager import RobotSetupManager
from test_robot_profiles_state import fixture
from test_robot_setup_manager import single_profile


def registry():
    from robot_agent_brain.scene.component_reference_registry import ComponentReferenceRegistry
    return ComponentReferenceRegistry({
        "VendorLabel": {"no_object_references": True},
        "VendorLink": {"references": [{"path": ["target_object_id"], "shape": "single", "target_type": "robot"},
                                       {"path": ["nested", "objects"], "shape": "list"},
                                       {"path": ["slots"], "shape": "map_values", "nullable": True}]},
    })


def test_declared_custom_references_remap_exactly_and_keep_other_numbers():
    _, scene, _ = fixture()
    scene.objects[-1].components.extend([
        SceneComponent(component_type="VendorLabel", properties={"number_not_id": 2}),
        SceneComponent(component_type="VendorLink", properties={"target_object_id": 2,
            "nested": {"objects": [2, 7]}, "slots": {"a": 3, "b": None}, "other_number": 7})])
    result = remap_scene(scene, new_scene_id=50, next_object_id=100, reference_registry=registry())
    props = result.scene.objects[-1].components[-1].properties
    assert props == {"target_object_id": 100, "nested": {"objects": [100, 102]},
                     "slots": {"a": 101, "b": None}, "other_number": 7}
    assert result.scene.objects[-1].components[-2].properties == {"number_not_id": 2}
    assert scene.objects[-1].components[-1].properties["target_object_id"] == 2


def test_same_rules_apply_to_robot_template_and_retained_components():
    _, scene, _ = fixture()
    scene.objects[-1].components.append(SceneComponent(component_type="VendorLabel", properties={"note": "keep"}))
    target = single_profile()
    target.template.objects[0].components.append(SceneComponent(component_type="VendorLink", properties={
        "target_object_id": 2, "nested": {"objects": [2]}, "slots": {"self": 2}}))
    result = RobotSetupManager(reference_registry=registry()).prepare(scene, current_robot_ids={2, 3},
        target_profile=target, platform_bindings={}, next_object_id=100)
    assert result.scene.objects[0].components[-1].properties == {"note": "keep"}
    assert result.scene.objects[-1].components[-1].properties["target_object_id"] == 100


@pytest.mark.parametrize("value", [999, 7, True])
def test_reference_missing_wrong_type_or_non_id_fails(value):
    _, scene, _ = fixture()
    scene.objects[-1].components.append(SceneComponent(component_type="VendorLink", properties={
        "target_object_id": value, "nested": {"objects": []}, "slots": {}}))
    with pytest.raises(ValueError):
        remap_scene(scene, new_scene_id=50, next_object_id=100, reference_registry=registry())


def test_robot_switch_cleans_removed_dialogue_ids_and_checkpoint_restores(tmp_path):
    from test_dual_session_pipeline import configured
    from robot_agent_brain.session.store import SessionStore
    session, _ = configured()
    session.dialogue.last_entity_id = 2
    session.dialogue.last_entity_ids = [2, 7]
    session.switch_robot_setup(single_profile(), platform_bindings={})
    assert session.dialogue.last_entity_ids == [7] and session.dialogue.last_entity_id == 7
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
        assert store.load("s").dialogue == session.dialogue

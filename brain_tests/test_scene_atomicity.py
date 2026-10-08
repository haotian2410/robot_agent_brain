import pytest
from robot_agent_brain.contracts.scene import SceneConfig, SceneComponent, ScenePatch, ScenePatchOperation, PatchAction
from robot_agent_brain.scene.scene_manager import SceneManager
from test_component_runtime import object_


def manager():
    return SceneManager(SceneConfig(scene_schema_version=1, scene_version=0, scene_id=1, scene_name="s",
                                    objects=[object_(0, "apple")]))


def patch(version, operations):
    return ScenePatch(scene_id=1, base_scene_version=version, operations=operations)


def test_retired_id_rejected_across_patches_and_within_same_patch():
    for same_patch in (True, False):
        state = manager()
        obj = state.scene.objects[0].model_copy(deep=True)
        remove = ScenePatchOperation(action="remove_object", object_id_in_scene=0)
        add = ScenePatchOperation(action="add_object", object_id_in_scene=0, object=obj)
        if not same_patch:
            state.apply_patch(patch(0, [remove]))
        before = state.scene.model_dump()
        with pytest.raises(ValueError, match="scene_object_id_reused"):
            state.apply_patch(patch(state.scene.scene_version, [remove, add] if same_patch else [add]))
        assert state.scene.model_dump() == before


def test_later_failure_never_commits_first_operation():
    state = manager()
    before = state.scene.model_dump()
    with pytest.raises(ValueError, match="scene_object_missing"):
        state.apply_patch(patch(0, [
            ScenePatchOperation(action="upsert_component", object_id_in_scene=0,
                component=object_(0, position=(1,0,0)).components[0]),
            ScenePatchOperation(action="remove_object", object_id_in_scene=999)]))
    assert state.scene.model_dump() == before


def test_copy_bypass_invalid_transform_revalidated():
    state = manager()
    invalid = object_(0).components[0].model_copy(deep=True)
    invalid.properties["scale"] = [0, 1, 1]
    op = ScenePatchOperation.model_construct(action=PatchAction.UPSERT_COMPONENT, object_id_in_scene=0,
                                            component=invalid, object=None, component_type=None)
    value = ScenePatch.model_construct(scene_id=1, base_scene_version=0, operations=[op])
    with pytest.raises(ValueError):
        state.apply_patch(value)
    assert state.scene.scene_version == 0


def test_payloads_are_exclusive():
    with pytest.raises(ValueError, match="scene_patch_payload_mismatch"):
        ScenePatchOperation(action="remove_object", object_id_in_scene=0, component=object_(0).components[0])

import pytest
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, ScenePatch, ScenePatchOperation, Transform, PatchAction
from robot_agent_brain.scene.scene_manager import SceneManager


def manager():
    return SceneManager(SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="a", asset_id="apple",
                                                                     semantic_name="apple", category="fruit")]))


def patch(version, operations):
    return ScenePatch(scene_id="s", base_scene_version=version, operations=operations)


def test_retired_id_rejected_across_patches_and_within_same_patch():
    for same_patch in (True, False):
        state = manager()
        obj = state.scene.objects[0].model_copy(deep=True)
        remove = ScenePatchOperation(action="remove", scene_object_id="a")
        add = ScenePatchOperation(action="add", scene_object_id="a", object=obj)
        if not same_patch:
            state.apply_patch(patch(0, [remove]))
        before = state.scene.model_dump()
        with pytest.raises(ValueError, match="scene_object_id_retired"):
            state.apply_patch(patch(state.scene.scene_version, [remove, add] if same_patch else [add]))
        assert state.scene.model_dump() == before


def test_later_failure_never_commits_first_operation():
    state = manager()
    before = state.scene.model_dump()
    with pytest.raises(ValueError, match="scene_object_missing"):
        state.apply_patch(patch(0, [
            ScenePatchOperation(action="update_transform", scene_object_id="a", transform=Transform(position=(1,0,0))),
            ScenePatchOperation(action="remove", scene_object_id="missing")]))
    assert state.scene.model_dump() == before


def test_copy_bypass_invalid_transform_revalidated():
    state = manager()
    invalid = Transform().model_copy(update={"scale": (0,1,1)})
    op = ScenePatchOperation.model_construct(action=PatchAction.UPDATE_TRANSFORM, scene_object_id="a", transform=invalid,
                                            object=None, properties=None)
    value = ScenePatch.model_construct(scene_id="s", base_scene_version=0, operations=[op])
    with pytest.raises(ValueError):
        state.apply_patch(value)
    assert state.scene.scene_version == 0


def test_payloads_are_exclusive():
    with pytest.raises(ValueError, match="scene_patch_payload_mismatch"):
        ScenePatchOperation(action="remove", scene_object_id="a", transform=Transform())

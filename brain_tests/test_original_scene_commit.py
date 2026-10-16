import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.scene import SceneSnapshot
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.original_scene_store import OriginalSceneStore
from test_robot_profiles_state import fixture


def session_store(tmp_path):
    _, original, _ = fixture()
    session = BrainSession(original, None, LocalScenePlatform())
    store = OriginalSceneStore(tmp_path)
    session.original_scene_manifest = store.capture_once(original, platform_object_ids={2, 3}, request_id="first", source="fixture")
    return session, store


def test_repeated_original_edits_start_from_same_snapshot_and_fresh_ids(tmp_path):
    session, store = session_store(tmp_path)
    source = (tmp_path / "original_scene.json").read_bytes()
    def edit(scene):
        scene.objects[-1].object_name_in_scene = "first-change"
        return scene
    first = session.derive_original_scene(store, edit, reset_allowed=True)
    first_ids = {o.object_id_in_scene for o in first.scene.objects}
    assert min(first_ids) >= 8
    second = session.derive_original_scene(store, lambda scene: scene, reset_allowed=True)
    assert not first_ids & {o.object_id_in_scene for o in second.scene.objects}
    assert second.scene.objects[-1].object_name_in_scene != "first-change"
    assert (tmp_path / "original_scene.json").read_bytes() == source
    assert second.scene.scene_version == 1 and first.scene.scene_id != second.scene.scene_id


def test_rejected_platform_keeps_current_scene_and_allocator(tmp_path):
    session, store = session_store(tmp_path)
    before, next_id = session.scene, session.next_scene_object_id
    class Reject(LocalScenePlatform):
        def load_scene(self, scene):
            return SceneSnapshot(scene_id=scene.scene_id, scene_version=scene.scene_version, accepted=False, error="fixture_rejected")
    session.platform = Reject()
    with pytest.raises(ValueError, match="fixture_rejected"):
        session.derive_original_scene(store, lambda scene: scene, reset_allowed=True)
    assert session.scene == before and session.next_scene_object_id == next_id
    assert session.sync_state == "unknown"


def test_edit_failure_and_missing_reset_permission_have_no_side_effects(tmp_path):
    session, store = session_store(tmp_path)
    before = session.scene
    with pytest.raises(ValueError, match="not_permitted"):
        session.derive_original_scene(store, lambda scene: scene)
    def fail(scene):
        raise ValueError("fixture_geometry_rejected")
    with pytest.raises(ValueError, match="geometry_rejected"):
        session.derive_original_scene(store, fail, reset_allowed=True)
    assert session.scene == before and session.sync_state == "synchronized"


def test_original_restore_restores_single_profile_from_current_dual(tmp_path):
    from test_robot_config_turns import session as configured_session
    from robot_agent_brain.contracts.turn import BrainTurn
    current = configured_session()
    current.process_turn("single", BrainTurn(status="accepted", turn_kind="robot_config", instruction="单臂", robot_setup_request={"mode": "single"}))
    store = OriginalSceneStore(tmp_path)
    current.original_scene_manifest = store.capture_once(current.scene, platform_object_ids=current.platform_object_ids,
        request_id="single-original", source="fixture", robot_setup=current.robot_setup, profile_object_map=current.profile_object_map)
    current.process_turn("dual", BrainTurn(status="accepted", turn_kind="robot_config", instruction="双臂", robot_setup_request={"mode": "dual"}))
    assert current.robot_setup.mode == "dual"
    original, _ = store.load()
    result = current.derive_original_scene(store, lambda scene: scene, reset_allowed=True)
    assert current.robot_setup.mode == "single"
    assert current.profile_object_map is not None
    assert not current.arm_states.arms["single"].state_known
    assert set(current.profile_object_map.values()) <= {o.object_id_in_scene for o in result.scene.objects}

import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionStore
from test_dual_recovery import failed_session, arguments
from test_dual_delivery import prepared


class RecordingPlatform(LocalScenePlatform):
    def __init__(self):
        super().__init__()
        self.loads = []

    def load_scene(self, scene):
        self.loads.append(scene.model_copy(deep=True))
        return super().load_scene(scene)


@pytest.mark.parametrize("mode", ["unknown", "pending", "synchronized"])
def test_restart_does_not_reset_uncertain_external_scene(tmp_path, mode):
    if mode == "unknown":
        session, _, _ = failed_session()
    else:
        session, commands = prepared()
        if mode == "pending":
            session.mark_dispatched(commands)
    store = SessionStore(tmp_path)
    store.save("s", session, revision=1)
    platform = RecordingPlatform()
    restored = store.restore(store.load("s"), BrainSession(None, session.pipeline, platform,
        robot_profiles=session.robot_profiles))
    assert len(platform.loads) == (1 if mode == "synchronized" else 0)
    assert restored.scene == session.scene
    assert restored.sync_state == session.sync_state
    assert restored.pending_commands == session.pending_commands
    assert restored.robot_setup == session.robot_setup
    assert restored.arm_states == session.arm_states
    if mode == "unknown":
        restored.reconcile_scene_and_robot_state(**arguments(restored))
        assert len(platform.loads) == 1


@pytest.mark.parametrize("separate,fail_understanding", [(False, False), (True, False), (False, True)])
def test_import_freezes_before_first_edit_or_understanding(tmp_path, separate, fail_understanding):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from robot_agent_brain.contracts.turn import BrainTurn
    from robot_agent_brain.session.original_scene_store import OriginalSceneStore
    from test_application_artifacts import Provider
    from test_query_scene_continuity import supported_scene
    from test_scene_replace import plan
    scene = supported_scene()
    path = tmp_path / "input.json"
    path.write_text(scene.model_dump_json())
    turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="把苹果向右移动10厘米",
        scene_edit=plan([{"operation": "translate", "target": "old", "direction": "right", "distance_m": .1}]))
    provider = Provider(turn)
    if fail_understanding:
        def fail(*args, **kwargs):
            raise ValueError("understanding unavailable")
        provider.understand_turn = fail
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path / "out"),
        scene_platform_object_ids={0}), provider=provider)
    if separate:
        app.load_scene("s", path)
        assert app.store.load("s").original_scene_manifest is not None
    report = app.handle("把苹果向右移动10厘米", session_id="s", scene_path=None if separate else path)
    original, _ = OriginalSceneStore(tmp_path / "out" / "s").load()
    assert original == scene
    if not fail_understanding:
        assert report.run_status == "success", report
        assert app.get_session("s").scene != scene


@pytest.mark.parametrize("route", ["feedback", "recovery"])
@pytest.mark.parametrize("tamper", ["metadata", "driver", "driver_connections", "reference"])
def test_confirmed_snapshot_validates_deployment_and_custom_references(route, tamper):
    from robot_agent_brain.contracts.feedback_v3 import ExecutionFeedbackV3
    from robot_agent_brain.contracts.scene import SceneComponent
    from robot_agent_brain.scene.component_access import SceneIndex
    from robot_agent_brain.scene.component_reference_registry import ComponentReferenceRegistry
    if route == "recovery":
        session, _, _ = failed_session()
    else:
        session, commands = prepared()
        session.mark_dispatched(commands)
    candidate = session.scene.model_copy(deep=True)
    candidate.scene_version += 1
    if tamper == "metadata":
        SceneIndex(candidate).component(2, "MetadataRef").properties["path"] = "$LIBRARY_SERVER/1"
    elif tamper == "driver":
        SceneIndex(candidate).component(2, "RobotDriver").properties["joint_sequence"] = ["wrong_joint"]
    elif tamper == "driver_connections":
        SceneIndex(candidate).component(2, "RobotDriver").properties["available_connect_joints"] = ["joint1"]
    else:
        session.reference_registry = ComponentReferenceRegistry({"Link": {"references": [{"path": ["target"]}]}})
        candidate.objects[0].components.append(SceneComponent(component_type="Link", properties={"target": 9999}))
    platform = RecordingPlatform()
    type(candidate).model_validate(candidate.model_dump())  # valid Scene JSON is not deployment proof
    session.platform = platform
    before = session.scene
    with pytest.raises(ValueError):
        if route == "recovery":
            session.reconcile_scene_and_robot_state(**(arguments(session) | {"confirmed_scene": candidate}))
        else:
            feedback = ExecutionFeedbackV3(request_id="fixture", scene_id=1, scene_version=1,
                robot_setup_revision=1, status="partial", actions=[{"step_id": "stage-1",
                "command_id": "command-1", "arm": "left", "status": "success"}], arms={"left": {"state_known": True}})
            session.apply_execution_feedback(feedback, confirmed_scene=candidate)
    assert platform.loads == []
    assert session.scene == before

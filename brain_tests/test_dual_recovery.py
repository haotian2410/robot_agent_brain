import pytest

from robot_agent_brain.contracts.feedback_v3 import ExecutionFeedbackV3
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionStore
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from test_coordinated_validator import runtime
from test_dual_session_pipeline import configured
from test_dual_coordinated_capability import task


def failed_session():
    session, registry = configured()
    commands = session.process_turn("failed", task()).commands
    session.mark_dispatched(commands)
    stage = commands.steps[0]
    feedback = ExecutionFeedbackV3(request_id="failed", scene_id=session.scene.scene_id,
        scene_version=session.scene.scene_version, robot_setup_revision=session.robot_setup_revision,
        status="partial", actions=[{"step_id": stage.step_id, "command_id": getattr(stage.arms, side).command_id,
                                   "arm": side, "status": status} for side, status in (("left", "success"), ("right", "failed"))],
        arms={"left": {"state_known": True}})
    session.apply_execution_feedback(feedback)
    return session, registry, commands


def arguments(session):
    scene = session.scene.model_copy(update={"scene_version": session.scene.scene_version + 1})
    return dict(confirmed_scene=scene, confirmed_arms=runtime(), source_request_id="failed",
                robot_setup_revision=session.robot_setup_revision, source="external")


def test_partial_unknown_then_authoritative_reconciliation_preserves_setup(tmp_path):
    session, registry, commands = failed_session()
    assert session.sync_state == "unknown" and session.pending_commands is None
    with pytest.raises(ValueError, match="scene_sync"):
        session.process_turn("blocked", task())
    setup = session.robot_setup.model_copy(deep=True)
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
        session = store.restore(store.load("s"), BrainSession(None, session.pipeline, LocalScenePlatform(), robot_profiles=registry))
    session.reconcile_scene_and_robot_state(**arguments(session))
    assert session.sync_state == "synchronized"
    assert session.robot_setup == setup and session.robot_setup_revision == 1
    assert not session.exported_commands
    with pytest.raises(ValueError):
        session.mark_dispatched(commands)
    assert session.process_turn("new", task()).commands.request_id == "new"


@pytest.mark.parametrize("bad", ["missing_scene", "old_version", "wrong_scene", "wrong_setup", "unknown_arm", "missing_arm", "bad_held", "source", "wrong_request", "changed_robot"])
def test_recovery_rejects_untrusted_or_stale_input_without_mutation(bad):
    session, _, _ = failed_session()
    args = arguments(session)
    if bad == "missing_scene": args["confirmed_scene"] = None
    if bad == "old_version": args["confirmed_scene"] = session.scene
    if bad == "wrong_scene": args["confirmed_scene"].scene_id = 999
    if bad == "wrong_setup": args["robot_setup_revision"] = 999
    if bad == "unknown_arm": args["confirmed_arms"].arms["right"].state_known = False
    if bad == "missing_arm": del args["confirmed_arms"].arms["right"]
    if bad == "bad_held": args["confirmed_arms"].arms["right"].holding_object = 999
    if bad == "source": args["source"] = "user_text"
    if bad == "wrong_request": args["source_request_id"] = "unrelated"
    if bad == "changed_robot":
        from robot_agent_brain.scene.component_access import SceneIndex
        SceneIndex(args["confirmed_scene"]).component(2, "MetadataRef").properties["path"] = "$LIBRARY_SERVER/1"
    before = (session.scene, session.arm_states.model_copy(deep=True), session.robot_setup.model_copy(deep=True))
    with pytest.raises(ValueError):
        session.reconcile_scene_and_robot_state(**args)
    assert (session.scene, session.arm_states, session.robot_setup) == before
    assert session.sync_state == "unknown"


def test_reconciliation_platform_timeout_keeps_unknown_and_retry_provenance():
    session, _, _ = failed_session()
    original = session.platform
    class Timeout:
        def load_scene(self, scene):
            raise TimeoutError("uncertain external commit")
    session.platform = Timeout()
    with pytest.raises(TimeoutError):
        session.reconcile_scene_and_robot_state(**arguments(session))
    assert session.sync_state == "unknown"
    session.platform = original
    session.reconcile_scene_and_robot_state(**arguments(session))
    assert session.sync_state == "synchronized"


@pytest.mark.parametrize("status,empty", [("failed", False), ("partial", False), ("partial", True)])
def test_feedback_status_matches_reported_actions(status, empty):
    session, _ = configured()
    commands = session.process_turn("r", task()).commands
    actions = [] if empty else [
        {"step_id": step.step_id, "command_id": getattr(step.arms, side).command_id,
         "arm": side, "status": "success"} for step in commands.steps for side in ("left", "right")]
    feedback = ExecutionFeedbackV3(request_id="r", scene_id=commands.scene_id, scene_version=commands.scene_version,
        robot_setup_revision=commands.robot_setup_revision, status=status, actions=actions,
        arms={"left": {"state_known": True, "holding_object": 7}, "right": {"state_known": True, "holding_object": 8}})
    with pytest.raises(ValueError, match="status_mismatch"):
        feedback.validate_against(commands, runtime())


def test_application_recovery_checkpoints_unknown_on_platform_error(tmp_path):
    from robot_agent_brain.application import BrainApplication
    from robot_agent_brain.config import BrainConfig
    from test_application_artifacts import Provider
    session, registry, _ = failed_session()
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path), robot_profiles=registry),
                           provider=Provider(task()))
    app.sessions["s"] = session
    class Timeout:
        def load_scene(self, scene):
            raise TimeoutError("platform unavailable")
    session.platform = Timeout()
    with pytest.raises(TimeoutError):
        app.reconcile_scene_and_robot_state("s", **arguments(session))
    saved = app.store.load("s")
    assert saved.sync_state == "unknown" and saved.recovery_context.request_id == "failed"
    assert saved.robot_setup == session.robot_setup
    session.platform = LocalScenePlatform()
    app.reconcile_scene_and_robot_state("s", **arguments(session))
    saved = app.store.load("s")
    assert saved.sync_state == "synchronized" and saved.recovery_context is None
    assert saved.exported_commands == {}

import json
from types import SimpleNamespace

import pytest

from robot_agent_brain.adapters.artifact_writer import ArtifactWriter
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.commands import canonical_commands, parse_commands
from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
from robot_agent_brain.contracts.feedback_v3 import ExecutionFeedbackV3
from robot_agent_brain.contracts.run_report import BrainRunReport
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionStore
from test_dual_commands_contract import example
from test_robot_profiles_state import fixture
from test_coordinated_validator import runtime


def prepared():
    _, scene, setup = fixture()
    session = BrainSession(scene, None, LocalScenePlatform())
    session.robot_setup = setup
    session.robot_setup_revision = 1
    session.arm_states = runtime()
    commands = CommandsFileV3.model_validate(example())
    session.exported_commands[commands.request_id] = canonical_commands(commands)
    return session, commands


def test_v3_artifacts_and_pending_checkpoint_preserve_null(tmp_path):
    session, commands = prepared()
    report = BrainRunReport(session_id="s", request_id="fixture", run_status="success", provider="replay")
    result = SimpleNamespace(commands=commands, scene_patch=None, scene_query_result=None)
    published = ArtifactWriter(tmp_path).publish(report, scene=session.scene, result=result)
    payload = json.loads(open(published.artifacts["commands"]).read())
    assert payload["steps"][0]["arms"]["right"] is None
    assert parse_commands(payload) == commands
    session.mark_dispatched(commands)
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
        state = store.load("s")
    restored = store.restore(state, BrainSession(None, None, LocalScenePlatform()))
    assert restored.pending_commands == payload
    assert restored.robot_setup == session.robot_setup


def test_partial_feedback_keeps_successful_arm_and_missing_peer_unknown():
    session, commands = prepared()
    session.mark_dispatched(commands)
    feedback = ExecutionFeedbackV3(request_id="fixture", scene_id=1, scene_version=1, robot_setup_revision=1,
        status="partial", actions=[{"step_id": "stage-1", "command_id": "command-1", "arm": "left", "status": "success"}],
        arms={"left": {"state_known": True}})
    assert session.apply_execution_feedback(feedback) == "partial"
    assert session.arm_states.arms["left"].state_known
    assert not session.arm_states.arms["right"].state_known
    assert session.sync_state == "unknown" and session.pending_commands is None
    with pytest.raises(ValueError, match="not_ready"):
        session.mark_dispatched(commands)


def test_wrong_setup_rejected_before_dispatch():
    session, commands = prepared()
    session.robot_setup_revision = 2
    with pytest.raises(ValueError, match="setup_mismatch"):
        session.mark_dispatched(commands)
    assert not session.dispatched_requests


def test_feedback_stage_and_success_evidence_checked():
    _, commands = prepared()
    data = {"request_id": "fixture", "scene_id": 1, "scene_version": 1, "robot_setup_revision": 1,
            "status": "success", "actions": [], "arms": {}}
    with pytest.raises(ValueError, match="incomplete_success"):
        ExecutionFeedbackV3.model_validate(data).validate_against(commands)
    data["status"] = "partial"
    data["actions"] = [{"step_id": "wrong", "command_id": "command-1", "arm": "left", "status": "success"}]
    with pytest.raises(ValueError, match="arm_or_stage"):
        ExecutionFeedbackV3.model_validate(data).validate_against(commands)


def test_feedback_cannot_cross_failed_barrier():
    from test_coordinated_validator import plan
    commands = plan([{"left": ("locate", {"target": 7}), "right": ("locate", {"target": 8})},
                     {"left": ("move", {"target": 7, "region": "grasp_region"})}])
    feedback = ExecutionFeedbackV3(request_id="fixture", scene_id=1, scene_version=1, robot_setup_revision=1,
        status="partial", actions=[
            {"step_id": "0", "command_id": "cmd-0-left", "arm": "left", "status": "success"},
            {"step_id": "0", "command_id": "cmd-0-right", "arm": "right", "status": "failed"},
            {"step_id": "1", "command_id": "cmd-1-left", "arm": "left", "status": "success"}])
    with pytest.raises(ValueError, match="barrier_violation"):
        feedback.validate_against(commands)

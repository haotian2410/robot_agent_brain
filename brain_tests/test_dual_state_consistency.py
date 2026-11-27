import pytest

from robot_agent_brain.contracts.feedback_v3 import ExecutionFeedbackV3
from robot_agent_brain.session.store import SessionState
from test_dual_session_pipeline import configured, task
from test_coordinated_validator import runtime
from test_robot_profiles_state import fixture


def test_success_cannot_claim_empty_after_successful_grasp():
    session, _ = configured()
    from test_coordinated_validator import plan
    from test_dual_delivery import historical_pending
    commands = plan([{"right": ("locate", {"target": 7})},
                     {"right": ("move", {"target": 7, "region": "grasp_region"})},
                     {"right": ("grasp", {"target": 7})}]).model_copy(update={"request_id": "r"})
    from robot_agent_brain.contracts.commands import canonical_commands
    session.exported_commands["r"] = canonical_commands(commands)
    historical_pending(session, commands)
    actions = [{"step_id": s.step_id, "command_id": s.arms.right.command_id, "arm": "right", "status": "success"} for s in commands.steps]
    feedback = ExecutionFeedbackV3(request_id="r", scene_id=session.scene.scene_id, scene_version=session.scene.scene_version,
        robot_setup_revision=session.robot_setup_revision, status="success", actions=actions,
        arms={"left": {"state_known": True}, "right": {"state_known": True}})
    with pytest.raises(ValueError, match="success_holding_mismatch"):
        session.apply_execution_feedback(feedback)
    assert session.pending_execution_request == "r"


def test_external_state_confirmation_is_versioned_and_invalidates_old_plan():
    from test_dual_v4_pipeline import setup
    session = setup()
    session.process_turn("old", task())
    args = dict(scene_id=session.scene.scene_id, scene_version=session.scene.scene_version,
                robot_setup_revision=session.robot_setup_revision)
    with pytest.raises(ValueError, match="stale"):
        session.confirm_robot_state(runtime(), **{**args, "robot_setup_revision": 999})
    assert "old" in session.exported_commands
    session.confirm_robot_state(runtime(right=7), **args)
    assert session.arm_states.arms["right"].holding_object == 7
    assert not session.exported_commands
    assert session.last_feedback_source == "external"


def test_profile_rejects_different_robot_resource_at_same_id():
    registry, scene, _ = fixture()
    scene = scene.model_copy(deep=True)
    from robot_agent_brain.scene.component_access import SceneIndex
    SceneIndex(scene).component(2, "MetadataRef").properties["path"] = "$LIBRARY_SERVER/1"
    with pytest.raises(ValueError, match="resource_mapping_mismatch"):
        registry.profiles["fixture_only"].validate_scene(scene)

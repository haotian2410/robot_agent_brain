import pytest
from robot_agent_brain.planning.dual_qwen_planner import DualQwenPlanner
from robot_agent_brain.planning.dual_arm_recipe_planner import DualArmRecipePlanner


@pytest.mark.parametrize("planner", [DualQwenPlanner, DualArmRecipePlanner])
def test_legacy_planner_import_cannot_execute_staged_runtime(planner):
    with pytest.raises(ValueError, match="staged_dual_v3_retired"):
        planner().plan()


def test_historical_v3_dispatch_is_rejected_before_state_access():
    from types import SimpleNamespace
    from robot_agent_brain.session.brain_session import BrainSession
    session = BrainSession(None, None, None)
    with pytest.raises(ValueError, match="staged_dual_v3_retired"):
        session.mark_dispatched(SimpleNamespace(schema_version="3.0"))
    assert session.pending_execution_request is None
    assert not session.dispatched_requests


def test_new_planning_result_cannot_wrap_historical_v3_commands():
    from robot_agent_brain.pipeline import BrainResult
    from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
    from test_dual_commands_contract import example
    historical = CommandsFileV3.model_validate(example())
    with pytest.raises(ValueError):
        BrainResult(commands=historical)
    # Historical parsing itself remains available at its explicit boundary.
    from robot_agent_brain.contracts.commands import parse_commands
    assert parse_commands(example()) == historical

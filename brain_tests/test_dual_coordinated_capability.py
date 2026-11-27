import pytest

from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_dual_v4_pipeline import setup
from test_layout_qwen_planning import provider_for


def task(parallel=True):
    # Retain the helper argument for historical recovery fixtures; it no
    # longer encodes Brain-owned synchronization in the semantic payload.
    return TaskParseOutput.model_validate({
        "entities": [{"id": name, "name": name, "category": "fruit"} for name in ("apple", "banana")],
        "operations": [{"type": "grasp", "target": name, "arm": side}
                       for name, side in (("apple", "left"), ("banana", "right"))],
    }).to_brain_turn("分别抓苹果和香蕉")


@pytest.mark.parametrize("mode", ["recipe", "qwen"])
def test_ordinary_dual_skills_do_not_require_coordinated_execution_flag(mode):
    session = setup(mode)
    session.robot_profiles.profiles["fixture_only"].coordinated_execution = False
    requests = []
    if mode == "qwen":
        session.pipeline.skill_planner.provider = provider_for({"operations": [
            {"operation_id": op, "steps": [{"skill_name": "pick", "parameters": {"source": oid}}]}
            for op, oid in (("op-1", 7), ("op-2", 8))]}, requests)
    result = session.process_turn("ordinary", task())
    assert result.commands.schema_version == "4.1"
    assert all(not command.depends_on for command in result.commands.commands)
    assert not {"resource_groups", "hold_constraints", "sync_groups"} & result.commands.model_dump().keys()
    if mode == "qwen":
        assert len(requests) == 1


def test_planning_capability_does_not_authorize_unsupported_live_dispatch():
    session = setup()
    result = session.process_turn("ordinary", task())
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        session.mark_dispatched(result.commands)
    assert session.pending_commands is None
    assert not session.dispatched_requests

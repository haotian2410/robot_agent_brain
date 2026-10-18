import pytest

from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_dual_session_pipeline import configured
from test_dual_qwen_planner import Provider


def task(parallel=True):
    return TaskParseOutput.model_validate({
        "entities": [{"id": name, "name": name, "category": "fruit"} for name in ("apple", "banana")],
        "operations": [{"type": "grasp", "target": name, "arm": side,
                        "parallel_group": "optional" if parallel else None, "parallel_required": False}
                       for name, side in (("apple", "left"), ("banana", "right"))],
    }).to_brain_turn("分别抓苹果和香蕉")


def model_output():
    return {"stages": [{side: {"operation_id": op, "skill": skill, "target_role": "target", "region": region}
                        for side, op in (("left", "op-1"), ("right", "op-2"))}
                       for skill, region in (("locate", None), ("move", "grasp_region"), ("grasp", None))]}


@pytest.mark.parametrize("mode", ["recipe", "qwen"])
def test_optional_parallel_still_requires_final_coordinated_capability(mode):
    session, registry = configured(mode)
    registry.profiles["fixture_only"].coordinated_execution = False
    if mode == "qwen":
        session.pipeline.skill_planner.provider = Provider(model_output())
    with pytest.raises(ValueError, match="dual_coordinated_execution_not_registered"):
        session.process_turn("parallel", task())
    assert not session.exported_commands


def test_v3_serial_consumer_does_not_require_parallel_capability():
    session, registry = configured()
    registry.profiles["fixture_only"].coordinated_execution = False
    result = session.process_turn("serial", task(False))
    assert result.commands.schema_version == "3.0"
    assert all(step.arms.left is None or step.arms.right is None for step in result.commands.steps)
    session.mark_dispatched(result.commands)


def test_dispatch_rechecks_changed_profile_capability():
    session, registry = configured()
    result = session.process_turn("parallel", task())
    registry.profiles["fixture_only"].coordinated_execution = False
    with pytest.raises(ValueError, match="dual_coordinated_execution_not_registered"):
        session.mark_dispatched(result.commands)
    assert session.pending_commands is None


def test_dispatch_rejects_changed_profile_instance_mapping():
    session, registry = configured()
    result = session.process_turn("old", task(False))
    profile = registry.profiles["fixture_only"]
    profile.setup.arms["left"].robot_object_id = 3
    profile.setup.arms["right"].robot_object_id = 2
    with pytest.raises(ValueError, match="setup_mismatch"):
        session.mark_dispatched(result.commands)

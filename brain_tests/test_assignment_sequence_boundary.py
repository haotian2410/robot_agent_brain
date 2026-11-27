import pytest
from robot_agent_brain.planning.arm_assignment import ArmAssignmentStep, ArmAssignmentPlan


@pytest.mark.parametrize("field", ["depends_on", "resource_groups", "hold_constraints", "sync_groups"])
def test_assignment_does_not_accept_scheduling_fields(field):
    with pytest.raises(ValueError):
        ArmAssignmentStep.model_validate({"step_id": "op-1", "arm": "left", field: []})


def test_assignment_roundtrip_contains_only_identity_and_arm():
    plan = ArmAssignmentPlan(mode="dual_arm", steps=[
        {"step_id": "op-1", "arm": "left"}, {"step_id": "op-2", "arm": "right"}])
    assert plan.model_dump()["steps"] == [
        {"step_id": "op-1", "arm": "left"}, {"step_id": "op-2", "arm": "right"}]


def test_same_object_explicit_arms_remain_operation_local():
    from test_dual_v4_pipeline import setup
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    from robot_agent_brain.planning.arm_assignment_resolver import resolve_arms
    session = setup()
    task = GroundedTask(instruction="先左后右操作同一苹果", scene_id=1, scene_version=1,
        entities=[{"entity_id": "apple", "semantic_name": "apple", "category": "fruit", "scene_object_id": 7}],
        operations=[{"operation_id": "op-1", "task_type": "grasp", "target": "apple", "arm": "left"},
                    {"operation_id": "op-2", "task_type": "grasp", "target": "apple", "arm": "right",
                     "depends_on": ["op-1"]}])
    before = session.arm_states.model_dump()
    result = resolve_arms(task, session.robot_profiles.profiles["fixture_only"], runtime=session.arm_states)
    assert [op.arm for op in result.operations] == ["left", "right"]
    assert result.operations[1].depends_on == ["op-1"]
    assert session.arm_states.model_dump() == before

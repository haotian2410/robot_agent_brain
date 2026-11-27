"""4.1 keeps user ordering; Control owns holding and runtime waiting."""
import pytest
from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.planning.dual_arm_sequence import build_commands_sequence
from robot_agent_brain.planning.atomic_operation_ir import AtomicOperationIR


@pytest.mark.parametrize("field", ["hold_constraints", "resource_groups", "sync_groups", "conditions"])
def test_semantic_task_refuses_old_shared_scheduling(field):
    with pytest.raises(ValueError):
        TaskIntent.model_validate({"instruction": "fixture", "entities": [], "operations": [], field: []})


@pytest.mark.parametrize("dependent", [False, True])
def test_explicit_dependency_is_the_only_cross_arm_edge(dependent):
    operations = [
        AtomicOperationIR(operation_id="op-1", kind="grasp", arm="left", source_object_id=7),
        AtomicOperationIR(operation_id="op-2", kind="grasp", arm="right", source_object_id=7,
                          depends_on=["op-1"] if dependent else [])]
    steps = {op.operation_id: [
        {"skill_name": "locate", "parameters": {"target": 7}},
        {"skill_name": "pick", "parameters": {"target": 7}}] for op in operations}
    commands = build_commands_sequence(operations=operations, skill_steps=steps,
        request_id="temporal", scene_id=1, scene_version=1, scene_digest="bound",
        robot_setup_revision=1, skill_contract_revision="fixture-only")
    assert commands.commands[2].depends_on == (["L-op-1-2"] if dependent else [])
    assert commands.commands[3].depends_on == ["R-op-2-1"]
    assert not {"hold_constraints", "resource_groups", "sync_groups", "execution_policy"} & commands.model_dump().keys()

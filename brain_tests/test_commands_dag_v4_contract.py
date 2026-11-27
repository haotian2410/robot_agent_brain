import pytest
from pydantic import ValidationError

from robot_agent_brain.contracts.commands_dag_v4 import CommandsFileV4
from robot_agent_brain.planning.dual_arm_dag import build_commands_dag
from robot_agent_brain.planning.atomic_operation_ir import AtomicOperationIR


def test_dag_rejects_unknown_dependency():
    with pytest.raises(ValidationError):
        CommandsFileV4(schema_version="4.1", request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
                       robot_setup_revision=0, skill_contract_revision="s",
                       commands=[{"command_id": "c1", "operation_id": "o1", "arm": "left",
                                  "skill_name": "pick", "depends_on": ["missing"]}])


def test_dag_rejects_cycle():
    with pytest.raises(ValidationError):
        CommandsFileV4(schema_version="4.1", request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
                       robot_setup_revision=0, skill_contract_revision="s", commands=[
            {"command_id": "c1", "operation_id": "o1", "arm": "left", "skill_name": "pick", "depends_on": ["c2"]},
            {"command_id": "c2", "operation_id": "o2", "arm": "left", "skill_name": "put", "depends_on": ["c1"]},
        ])


def test_dag_builder_orders_same_arm_and_keeps_parallel_arms():
    ops = [
        type("Op", (), {"operation_id": "o1", "arm": "left", "depends_on": []})(),
        type("Op", (), {"operation_id": "o2", "arm": "right", "depends_on": []})(),
    ]
    result = build_commands_dag(
        request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
        robot_setup_revision=0, skill_contract_revision="s", operations=ops,
        skill_steps={"o1": [{"skill_name": "pick"}], "o2": [{"skill_name": "put"}]})
    assert {item.arm for item in result.commands} == {"left", "right"}


def test_dag_builder_from_ir_keeps_cross_arm_dependency():
    from robot_agent_brain.planning.dual_arm_dag import build_commands_dag_from_ir
    ops = [AtomicOperationIR(operation_id="o1", kind="pick_and_place", arm="left"),
           AtomicOperationIR(operation_id="o2", kind="pick_and_place", arm="right", depends_on=["o1"])]
    result = build_commands_dag_from_ir(
        request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
        robot_setup_revision=0, skill_contract_revision="s", operations=ops,
        skill_steps={"o1": [{"skill_name": "pick"}], "o2": [{"skill_name": "put"}]})
    assert result.commands[1].depends_on == ["L-o1-1"]


def test_operation_skill_chain_is_serial_without_model_dependencies():
    result = build_commands_dag(
        request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
        robot_setup_revision=0, skill_contract_revision="s",
        operations=[AtomicOperationIR(operation_id="o1", kind="pick_and_place", arm="left")],
        skill_steps={"o1": [{"skill_name": "pick"}, {"skill_name": "put"}]})
    assert result.commands[1].depends_on == [result.commands[0].command_id]


def test_same_arm_transitive_order_is_accepted():
    result = CommandsFileV4(
        schema_version="4.1", request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
        robot_setup_revision=0, skill_contract_revision="s", commands=[
            {"command_id": "a", "operation_id": "o1", "arm": "left", "skill_name": "pick"},
            {"command_id": "b", "operation_id": "o2", "arm": "right", "skill_name": "pick", "depends_on": ["a"]},
            {"command_id": "c", "operation_id": "o3", "arm": "left", "skill_name": "put", "depends_on": ["b"]},
        ])
    assert result.commands[-1].depends_on == ["b"]


@pytest.mark.parametrize("field,value", [("depends_on", []), ("arm", "right"), ("resource_groups", [])])
def test_skill_draft_cannot_schedule_or_reassign(field, value):
    with pytest.raises(ValidationError):
        build_commands_dag(request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
            robot_setup_revision=0, skill_contract_revision="s",
            operations=[AtomicOperationIR(operation_id="o1", kind="pick_and_place", arm="left")],
            skill_steps={"o1": [{"skill_name": "pick", field: value}]})


def test_extra_operation_is_not_silently_ignored():
    with pytest.raises(ValueError, match="operation_coverage_invalid"):
        build_commands_dag(request_id="r", scene_id=1, scene_version=1, scene_digest="a" * 64,
            robot_setup_revision=0, skill_contract_revision="s",
            operations=[AtomicOperationIR(operation_id="o1", kind="pick_and_place", arm="left")],
            skill_steps={"o1": [{"skill_name": "pick"}], "invented": [{"skill_name": "put"}]})


def test_dual_draft_requires_exact_operation_coverage():
    from robot_agent_brain.contracts.dual_skill_draft import DualSkillDraft
    draft = DualSkillDraft(operations=[{"operation_id": "o1", "steps": [{"skill_name": "pick"}]}])
    assert draft.steps_for(["o1"]) == {"o1": [{"skill_name": "pick", "parameters": {}}]}
    with pytest.raises(ValueError, match="operation_coverage_invalid"):
        draft.steps_for(["o1", "o2"])

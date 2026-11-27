import pytest

from robot_agent_brain.planning.arm_assignment import ArmAssignmentOutput, validate_assignment_output


def assigned():
    return ArmAssignmentOutput(status="assigned", assignments=[
        {"operation_id": "a", "arm": "left"},
        {"operation_id": "b", "arm": "right"}],
        arm_order={"left": ["a"], "right": ["b"]})


def test_complete_assignment_preserves_locks():
    assert validate_assignment_output(assigned(), operation_ids=["a", "b"],
        locked_arms={"a": "left"}, both_required=True) == assigned()


@pytest.mark.parametrize("kwargs,code", [
    ({"operation_ids": ["a"]}, "coverage"),
    ({"operation_ids": ["a", "b"], "locked_arms": {"a": "right"}}, "locked"),
    ({"operation_ids": ["a", "b"], "same_arm_groups": [["a", "b"]]}, "continuity"),
])
def test_invalid_assignments_rejected(kwargs, code):
    with pytest.raises(ValueError, match=code):
        validate_assignment_output(assigned(), **kwargs)


def test_model_cannot_output_resource_or_dependency_decisions():
    data = assigned().model_dump()
    data["assignments"][0]["depends_on"] = ["b"]
    with pytest.raises(ValueError):
        ArmAssignmentOutput.model_validate(data)


def test_insufficient_evidence_is_not_success():
    with pytest.raises(ValueError, match="insufficient_evidence"):
        validate_assignment_output(ArmAssignmentOutput(status="insufficient_evidence"), operation_ids=["a"])

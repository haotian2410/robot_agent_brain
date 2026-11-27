import pytest
from jsonschema import ValidationError as SchemaValidationError

from robot_agent_brain.models.task_understanding import TaskParseWireOutput
from robot_agent_brain.models.understanding_wire import encode, decode


def task():
    return {"protocol_version": "task_understanding.v3.1", "status": "accepted",
            "turn_kind": "robot_task", "entities": [
                {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "operations": [{"operation": "grasp", "target": "apple", "arm": "left"}]}


@pytest.mark.parametrize("field,short", [
    ("parallel_group", "pg"), ("parallel_required", "pr"), ("same_arm_group", "sg"),
])
def test_retired_operation_fields_fail_full_and_compact(field, short):
    full = task()
    compact = encode(full)
    full["operations"][0][field] = None
    compact["o"][0][short] = None
    with pytest.raises(ValueError):
        TaskParseWireOutput.model_validate(full)
    with pytest.raises(SchemaValidationError):
        decode(compact)


def test_retired_hold_field_fails_even_when_empty():
    full = task()
    compact = encode(full)
    full["hold_constraints"] = []
    compact["hc"] = []
    with pytest.raises(ValueError):
        TaskParseWireOutput.model_validate(full)
    with pytest.raises(SchemaValidationError):
        decode(compact)


def test_explicit_arm_and_dependency_survive_compact():
    full = task()
    full["operations"].append({"operation": "grasp", "target": "apple",
                               "arm": "right", "depends_on": ["op-1"]})
    wire = TaskParseWireOutput.model_validate(decode(encode(full)))
    intent = wire.to_task_intent("左臂先操作苹果，然后右臂操作苹果")
    assert [operation.arm for operation in intent.operations] == ["left", "right"]
    assert intent.operations[1].depends_on == ["op-1"]


def test_explicit_completion_order_cannot_silently_become_independent():
    full = task()
    full["operations"].append({"operation": "grasp", "target": "apple", "arm": "right"})
    wire = TaskParseWireOutput.model_validate(full)
    with pytest.raises(ValueError, match="task_explicit_dependency_missing"):
        wire.to_task_intent("先用左臂抓苹果，完成后再用右臂操作苹果")
    wire.operations[1].depends_on = ["op-1"]
    assert wire.to_task_intent("先用左臂抓苹果，完成后再用右臂操作苹果").operations[1].depends_on == ["op-1"]


def test_compact_requires_explicit_dependency_decision_even_when_empty():
    compact = encode(task())
    assert compact["o"][0]["dp"] == []
    compact["o"][0].pop("dp")
    with pytest.raises(SchemaValidationError):
        decode(compact)

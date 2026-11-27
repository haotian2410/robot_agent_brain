import pytest
from jsonschema import Draft202012Validator

from robot_agent_brain.contracts.commands_sequence_v41 import (
    CommandsFileV41, SHARED_METADATA, canonical_commands_v41,
)


def payload():
    return dict(schema_version="4.1", request_id="review", scene_id=1,
                scene_version=2, scene_digest="a" * 64, robot_setup_revision=1,
                skill_contract_revision="fixture-only", commands=[
                    dict(command_id="L-1", operation_id="op-1", arm="left",
                         skill_name="pick", parameters={"target": 7}, depends_on=[]),
                    dict(command_id="R-1", operation_id="op-2", arm="right",
                         skill_name="pick", parameters={"target": 7}, depends_on=[]),
                ])


def test_two_arms_same_object_are_not_a_scheduling_decision():
    result = canonical_commands_v41(CommandsFileV41.model_validate(payload()))
    assert not SHARED_METADATA.intersection(result)
    assert all(not command["depends_on"] for command in result["commands"])
    Draft202012Validator(CommandsFileV41.model_json_schema()).validate(result)


@pytest.mark.parametrize("field", sorted(SHARED_METADATA))
@pytest.mark.parametrize("value", [None, [], {}])
def test_shared_metadata_is_rejected_even_if_empty(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValueError, match="commands_v41_shared_metadata_forbidden"):
        CommandsFileV41.model_validate(data)
    assert not Draft202012Validator(CommandsFileV41.model_json_schema()).is_valid(data)


def test_parameter_keys_are_not_recursively_deleted_or_reinterpreted():
    data = payload()
    data["commands"][0]["parameters"] = {"effects": {"hold": "user-data"}}
    assert canonical_commands_v41(CommandsFileV41.model_validate(data)) == data


@pytest.mark.parametrize("fault,code", [
    ("unknown", "dependency_reference_invalid"),
    ("self", "dependency_reference_invalid"),
    ("duplicate", "dependency_reference_invalid"),
    ("cycle", "dependency_cycle"),
    ("same_arm", "same_arm_sequence_invalid"),
    ("operation_arm", "operation_arm_changed"),
])
def test_graph_rejection(fault, code):
    data = payload()
    left, right = data["commands"]
    if fault == "unknown":
        right["depends_on"] = ["missing"]
    elif fault == "self":
        right["depends_on"] = ["R-1"]
    elif fault == "duplicate":
        right["depends_on"] = ["L-1", "L-1"]
    elif fault == "cycle":
        left["depends_on"], right["depends_on"] = ["R-1"], ["L-1"]
    elif fault == "same_arm":
        right["arm"] = "left"
    else:
        right["operation_id"] = "op-1"
    with pytest.raises(ValueError, match="commands_v41_" + code):
        CommandsFileV41.model_validate(data)


def test_explicit_edge_and_single_active_arm_are_legal():
    data = payload()
    data["commands"][1]["depends_on"] = ["L-1"]
    CommandsFileV41.model_validate(data)
    data["commands"][1]["arm"] = "left"
    CommandsFileV41.model_validate(data)


@pytest.mark.parametrize("version", ["2.0", "3.0", "4.0"])
def test_no_implicit_protocol_upgrade(version):
    data = payload()
    data["schema_version"] = version
    with pytest.raises(ValueError):
        CommandsFileV41.model_validate(data)

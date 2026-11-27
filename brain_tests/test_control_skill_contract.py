import pytest
from robot_agent_brain.contracts.control_skill_contract import ControlSkillContract
from robot_agent_brain.planning.atomic_operation_ir import AtomicOperationIR
from robot_agent_brain.planning.dual_arm_dag import build_negotiated_commands_dag


def contract():
    return dict(revision="fixture-reviewed-v1", supported_protocols=["4.1"], expansion_level="task", operation_semantics={"grasp": {"required_skill_sequence": ["pick"]}},
        skills={"pick": {"expansion_level": "task", "parameters_schema": {
            "type": "object", "properties": {"source": {"type": "integer", "minimum": 0}},
            "required": ["source"], "additionalProperties": False}}})


def build(capabilities=None, **kwargs):
    return build_negotiated_commands_dag(skill_contract=capabilities or contract(),
        draft=kwargs.pop("draft", {"operations": [{"operation_id": "op1", "steps": [
            {"skill_name": "pick", "parameters": {"source": 7}}]}]}),
        operations=[AtomicOperationIR(operation_id="op1", kind="pick_and_place", arm="left")],
        request_id="request", scene_id=1, scene_version=2, scene_digest="a" * 64,
        robot_setup_revision=1, **kwargs)


def test_negotiated_builder_uses_contract_revision():
    result = build()
    assert result.skill_contract_revision == "fixture-reviewed-v1"
    assert result.commands[0].parameters == {"source": 7}


def test_v3_only_is_not_downgraded():
    data = contract()
    data["supported_protocols"] = ["3.0"]
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        build(data)


def test_unknown_skill_and_mixed_granularity_rejected():
    data = contract()
    data["skills"]["pick"]["expansion_level"] = "atomic"
    with pytest.raises(ValueError, match="expansion_level_mismatch"):
        build(data)
    with pytest.raises(ValueError, match="control_skill_unregistered"):
        build(draft={"operations": [{"operation_id": "op1", "steps": [{"skill_name": "grasp"}]}]})


@pytest.mark.parametrize("parameters", [{}, {"source": "7"}, {"source": -1}, {"source": 7, "xyz": [0, 0, 0]}])
def test_registered_parameter_schema_is_enforced(parameters):
    with pytest.raises(ValueError, match="control_skill_parameters_invalid"):
        build(draft={"operations": [{"operation_id": "op1", "steps": [
            {"skill_name": "pick", "parameters": parameters}]}]})


def test_stale_contract_and_unadvertised_resources_rejected():
    result = build()
    changed = ControlSkillContract.model_validate(contract()).model_copy(update={"revision": "new"})
    with pytest.raises(ValueError, match="revision_mismatch"):
        changed.validate_commands(result)



def test_skill_schema_cannot_fetch_external_references():
    data = contract()
    data["skills"]["pick"]["parameters_schema"] = {"$ref": "https://example.invalid/schema"}
    with pytest.raises(ValueError, match="external_reference"):
        ControlSkillContract.model_validate(data)


def test_unused_skill_cannot_mix_contract_granularity():
    data = contract()
    data["skills"]["unused"] = {"expansion_level": "atomic", "parameters_schema": {}}
    with pytest.raises(ValueError, match="control_skill_expansion_level_mismatch"):
        ControlSkillContract.model_validate(data)


@pytest.mark.parametrize("field", ["supports_sync", "supports_resources", "supports_hold"])
@pytest.mark.parametrize("value", ["true", "false", 0, 1])
def test_feature_support_requires_explicit_boolean(field, value):
    data = contract()
    data[field] = value
    with pytest.raises(ValueError):
        ControlSkillContract.model_validate(data)


@pytest.mark.parametrize("versions", [[""], ["4.1", "4.1"], [" 4.0"]])
def test_protocol_advertisement_has_unique_nonblank_exact_versions(versions):
    data = contract()
    data["supported_protocols"] = versions
    with pytest.raises(ValueError, match="control_skill_protocol_list_invalid"):
        ControlSkillContract.model_validate(data)


def test_unknown_future_version_is_preserved_but_does_not_authorize_v4():
    data = contract()
    data["supported_protocols"] = ["future-version"]
    value = ControlSkillContract.model_validate(data)
    assert value.supported_protocols == ["future-version"]
    with pytest.raises(ValueError, match="unsupported_protocol_version"):
        build(data)

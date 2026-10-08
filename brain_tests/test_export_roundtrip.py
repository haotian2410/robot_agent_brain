import json
import pytest
from pydantic import ValidationError
from jsonschema import Draft202012Validator
from robot_agent_brain.contracts.commands import CommandsFile, canonical_commands
from robot_agent_brain.adapters.json_command_sink import JsonCommandSink


def wire(skill, parameters):
    return dict(schema_version="2.0", request_id="r", scene_id=1, scene_version=0, robot="ur5e",
                operations=[dict(operation_id="op-1", semantic_intent="test")],
                commands=[dict(command_id="c1", source_skill_step_id="s1", operation_id="op-1",
                               skill_name=skill, parameters=parameters)])


VALID = [("locate", {"target": 0}), ("grasp", {"target": 0}),
         ("move", {"target": 0, "region": "grasp_region"}),
         ("move", {"target": 0, "motion_direction": "right", "distance_m": .1}),
         ("release", {"target": 0, "reference": 1, "region": "placement_region"}),
         ("press", {"target": 0, "region": "button_surface"}),
         ("pull", {"target": 0, "reference": 2}),
         ("push", {"target": 0, "reference": 2})]


@pytest.mark.parametrize("skill,params", VALID)
def test_final_file_passes_public_schema(tmp_path, skill, params):
    model = CommandsFile.model_validate(wire(skill, params))
    path = tmp_path / "commands.json"
    JsonCommandSink(path).write(model)
    payload = json.loads(path.read_text())
    Draft202012Validator(CommandsFile.model_json_schema()).validate(payload)
    assert payload == canonical_commands(model)
    assert payload["commands"][0]["parameters"] == params


@pytest.mark.parametrize("skill,params", VALID)
def test_every_skill_rejects_unknown_parameters(skill, params):
    payload = wire(skill, {**params, "trajectory": []})
    with pytest.raises(ValidationError):
        CommandsFile.model_validate(payload)
    assert not Draft202012Validator(CommandsFile.model_json_schema()).is_valid(payload)


@pytest.mark.parametrize("skill,params", [
    ("locate", {"target": 0, "region": "grasp_region"}),
    ("grasp", {"target": 0, "reference": 1}),
    ("release", {"target": 0, "distance_m": .1}),
    ("press", {"target": 0, "reference": 1}),
    ("pull", {"target": 0, "motion_direction": "right"}),
    ("push", {"target": 0, "distance_m": .1}),
    ("move", {"target": 0}),
    ("move", {"target": 0, "motion_direction": None, "distance_m": None}),
    ("move", {"target": 0, "region": "grasp_region", "motion_direction": "right", "distance_m": .1}),
    ("move", {"target": 0, "motion_direction": "right", "distance_m": float("inf")}),
])
def test_wrong_skill_parameters_fail_both_validators(skill, params):
    payload = wire(skill, params)
    with pytest.raises(ValidationError):
        CommandsFile.model_validate(payload)
    assert not Draft202012Validator(CommandsFile.model_json_schema()).is_valid(payload)


def test_failed_write_does_not_overwrite_existing_file(tmp_path):
    path = tmp_path / "commands.json"
    good = CommandsFile.model_validate(wire(*VALID[0]))
    JsonCommandSink(path).write(good)
    old = path.read_bytes()
    bad = good.model_copy(update={"scene_version": -1})
    with pytest.raises(ValidationError):
        JsonCommandSink(path).write(bad)
    assert path.read_bytes() == old

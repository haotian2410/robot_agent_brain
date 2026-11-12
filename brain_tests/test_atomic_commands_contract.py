"""The control atomic dialect: every parameter surface skill.md defines, and nothing else."""
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from robot_agent_brain.contracts.commands import canonical_commands, parse_commands
from robot_agent_brain.contracts.commands_atomic import (ApproachParameters, AtomicCommand, AtomicCommandsFile,
                                                         AtomicSkillName, LiftUpParameters, MoveToParameters,
                                                         PARAMETER_TYPES, PickParameters, PullPushParameters,
                                                         PutParameters, RetreatParameters, SearchParameters)


def skill(name, **parameters):
    return AtomicCommand(command_id="0", skill_name=name, parameters=parameters)


def document(*commands):
    """The Brain owns the sequential numbering, so the wire ids are always 1..N."""
    numbered = [item.model_copy(update={"command_id": str(index)})
                for index, item in enumerate(commands, 1)]
    return AtomicCommandsFile(request_id="r-1", scene_id=7, scene_version=3, commands=numbered)


def test_catalog_is_exactly_the_control_skills():
    assert [item.value for item in AtomicSkillName] == ["approach", "pick", "lift_up", "retreat", "move_to", "put",
                                                        "pull", "push", "release"]
    assert set(PARAMETER_TYPES) == set(AtomicSkillName)


@pytest.mark.parametrize("name,parameters,expected", [
    ("approach", {"target": 32}, ApproachParameters),
    ("pick", {"target": 32, "hold_force": 12.5}, PickParameters),
    ("lift_up", {"distance": 0.03}, LiftUpParameters),
    ("retreat", {"target": 32, "pose_axis": "-z"}, RetreatParameters),
    ("move_to", {"target": "home", "planning_method": "joint"}, MoveToParameters),
    ("put", {"target": 35, "relation": "front", "distance_m": 0.1}, PutParameters),
    ("pull", {"distance": 0.16, "frame": "grasp"}, PullPushParameters),
    ("push", {"distance": 0.16, "frame": "world", "direction": [-0.54, 0.84, 0.0]}, PullPushParameters),
])
def test_parameters_are_typed_by_skill(name, parameters, expected):
    assert isinstance(skill(name, **parameters).parameters, expected)


def test_stroke_is_a_bounded_vector_without_a_target():
    """skill.md makes ``distance`` required and leaves the drawer to the grip before it."""
    assert skill("pull", distance=0.16).parameters.frame is None
    for bad in ({"frame": "grasp"}, {"distance": 0}, {"distance": -0.1},
                {"distance": 0.16, "frame": "object"}, {"distance": 0.16, "direction": [1, 0]},
                {"distance": 0.16, "direction": [0, 0, 0]}, {"distance": 0.16, "direction": [float("inf"), 0, 0]},
                {"distance": 0.16, "target": 9}):
        with pytest.raises(ValidationError):
            skill("pull", **bad)


def test_parameters_are_closed_sets():
    with pytest.raises(ValidationError):
        AtomicCommand(command_id="1", skill_name="pick", parameters={"target": 1, "gripper": "close"})
    with pytest.raises(ValidationError):
        AtomicCommand(command_id="1", skill_name="lift_up", parameters={"target": 1})
    with pytest.raises(ValidationError):
        AtomicCommand(command_id="1", skill_name="go_home", parameters={"target": 1})


def test_search_ladder_keeps_only_structural_rules():
    """Control owns the default ladder, so the Brain checks its shape, not the 2cm/3cm minima."""
    ladder = {"min_distance": 0.02, "max_distance": 0.1, "step": 0.005}
    assert ApproachParameters(target=1, search=ladder).search.step == 0.005
    assert RetreatParameters(target=1, search=ladder).search.max_distance == 0.1
    for bad in ({"min_distance": 0.1, "max_distance": 0.02, "step": 0.005},
               {"min_distance": 0, "max_distance": 0.1, "step": 0.005},
               {"min_distance": 0.02, "max_distance": 0.1, "step": 0},
               {"min_distance": 0.02, "max_distance": float("inf"), "step": 0.005}):
        with pytest.raises(ValidationError):
            SearchParameters(**bad)


@pytest.mark.parametrize("parameters", [
    {"target": 1, "relation": "highest", "distance_m": 0.1},
    {"target": 1, "relation": "near"},
    {"target": 1, "distance_m": -0.1},
    {"target": 1, "relation": "front", "distance_m": float("nan")},
])
def test_put_rejects_unspelled_relations_and_malformed_offsets(parameters):
    with pytest.raises(ValidationError):
        PutParameters(**parameters)


@pytest.mark.parametrize("relation", ["above", "below"])
def test_put_accepts_the_world_z_release_control_added(relation):
    """``b24cc3f`` let ``put`` offset along Z, so the contract must spell it."""
    assert PutParameters(target=1, relation=relation, distance_m=0.1).relation == relation


def test_pick_force_and_lift_distance_are_positive_and_finite():
    for parameters in ({"target": 1, "hold_force": 0}, {"target": 1, "hold_force": float("inf")}):
        with pytest.raises(ValidationError):
            PickParameters(**parameters)
    for parameters in ({"distance": 0}, {"distance": -0.01}, {"distance": float("inf")}):
        with pytest.raises(ValidationError):
            LiftUpParameters(**parameters)


def test_distance_requires_a_relative_direction():
    with pytest.raises(ValidationError, match="distance_m requires"):
        PutParameters(target=1, distance_m=0.1)
    with pytest.raises(ValidationError, match="distance_m requires"):
        MoveToParameters(target=1, distance_m=0.1)
    with pytest.raises(ValidationError, match="relative direction"):
        PutParameters(target=1, relation="at", distance_m=0.1)
    assert PutParameters(target=1, relation="left", distance_m=0.0).distance_m == 0.0


def test_end_effector_moves_must_be_linear():
    assert MoveToParameters(target="end_effector").planning_method is None
    assert MoveToParameters(target="end_effector", planning_method="linear").planning_method == "linear"
    with pytest.raises(ValidationError, match="linear"):
        MoveToParameters(target="end_effector", planning_method="joint")


def test_move_relation_also_allows_vertical_targets():
    """Only `put` is horizontal; `move_to` keeps the above/below poses control supports."""
    assert MoveToParameters(target=1, relation="above", distance_m=0.05).relation == "above"


def test_document_is_the_only_wire_shape():
    payload = canonical_commands(document(
        skill("approach", target=32), skill("pick", target=32, hold_force=15.0), skill("lift_up", distance=0.02),
        skill("retreat", target=32), skill("move_to", target="home", planning_method="joint"),
        skill("approach", target=12), skill("put", target=12), skill("retreat", target=12)))
    assert payload["schema_version"] == "2.0" and payload["request_id"] == "r-1"
    assert (payload["scene_id"], payload["scene_version"]) == (7, 3)
    assert [item["command_id"] for item in payload["commands"]] == [str(i) for i in range(1, 9)]
    assert payload["commands"][2] == {"command_id": "3", "skill_name": "lift_up", "parameters": {"distance": 0.02}}
    assert "robot" not in payload and "operations" not in payload
    Draft202012Validator(AtomicCommandsFile.model_json_schema()).validate(payload)
    assert isinstance(parse_commands(json.loads(json.dumps(payload))), AtomicCommandsFile)


def test_optional_parameters_are_absent_not_null():
    assert canonical_commands(document(skill("pick", target=32)))["commands"][0]["parameters"] == {"target": 32}


def test_command_ids_must_be_unique_and_present():
    with pytest.raises(ValidationError, match="unique"):
        AtomicCommandsFile(request_id="r", scene_id=1, scene_version=0,
                           commands=[skill("approach", target=1), skill("approach", target=2)])
    with pytest.raises(ValidationError):
        AtomicCommandsFile(request_id="r", scene_id=1, scene_version=0, commands=[])


def test_legacy_dialects_still_parse_by_their_own_keys():
    legacy = {"schema_version": "2.0", "request_id": "r-1", "scene_id": 1, "scene_version": 0,
              "robot": "ur5e", "operations": [], "commands": []}
    assert parse_commands(legacy).__class__.__name__ == "CommandsFile"
    assert isinstance(parse_commands(canonical_commands(document(skill("approach", target=1)))), AtomicCommandsFile)
    with pytest.raises(ValueError, match="commands_schema_version_unsupported"):
        parse_commands({"schema_version": "9.9"})

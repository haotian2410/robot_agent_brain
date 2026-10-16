"""Protocol-only fixtures, not deployed Control profile/group registrations."""
import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from robot_agent_brain.contracts.commands_v3 import CommandsFileV3, canonical_commands_v3
from robot_agent_brain.contracts.robot_setup import RobotRuntimeState


def example():
    return {
        "schema_version": "3.0", "request_id": "fixture", "scene_id": 1,
        "scene_version": 1, "robot_setup_revision": 1,
        "robot_setup": {"profile_id": "fixture_only", "mode": "dual", "arms": {
            "left": {"robot_object_id": 2, "planning_group": "fixture_left", "end_effector": "fixture_tool", "gripper": "fixture_gripper"},
            "right": {"robot_object_id": 3, "planning_group": "fixture_right", "end_effector": "fixture_tool", "gripper": "fixture_gripper"}}},
        "operations": [{"operation_id": "op-1", "semantic_intent": "locate apple", "task_type": "locate", "target": 7, "arm": "left"}],
        "steps": [{"step_id": "stage-1", "semantic_intent": "locate apple", "arms": {
            "left": {"command_id": "command-1", "source_skill_step_id": "skill-1", "operation_id": "op-1",
                     "skill_name": "locate", "parameters": {"target": 7}}, "right": None}}],
    }


def test_null_slot_roundtrip_and_barrier_policy():
    value = CommandsFileV3.model_validate(example())
    wire = canonical_commands_v3(value)
    assert "right" in wire["steps"][0]["arms"] and wire["steps"][0]["arms"]["right"] is None
    assert wire["execution_policy"]["between_steps"] == "barrier"
    assert wire["execution_policy"]["on_failure"] == "stop_no_automatic_replay"
    assert CommandsFileV3.model_validate(wire) == value


def test_missing_or_empty_slots_rejected_by_model_and_json_schema():
    for arms in ({"left": None, "right": None}, {"left": example()["steps"][0]["arms"]["left"]}):
        data = example()
        data["steps"][0]["arms"] = arms
        with pytest.raises(ValueError):
            CommandsFileV3.model_validate(data)
        with pytest.raises(ValidationError):
            Draft202012Validator(CommandsFileV3.model_json_schema()).validate(data)


@pytest.mark.parametrize("field", ["command_id", "source_skill_step_id"])
def test_action_ids_unique_across_stages(field):
    data = example()
    second = copy.deepcopy(data["steps"][0])
    second["step_id"] = "stage-2"
    for key in ("command_id", "source_skill_step_id"):
        if key != field:
            second["arms"]["left"][key] += "-2"
    data["steps"].append(second)
    with pytest.raises(ValueError, match="duplicate_identifier"):
        CommandsFileV3.model_validate(data)


def test_wrong_arm_rejected():
    data = example()
    data["operations"][0]["arm"] = "right"
    with pytest.raises(ValueError, match="arm_assignment"):
        CommandsFileV3.model_validate(data)


def test_pour_skill_and_predicates_remain_unregistered():
    data = example()
    data["steps"][0]["arms"]["left"]["skill_name"] = "pour"
    with pytest.raises(ValueError):
        CommandsFileV3.model_validate(data)
    data = example()
    data["steps"][0]["preconditions"] = [{"predicate": "receiver_ready", "object_id": 7, "arm": "left"}]
    with pytest.raises(ValueError):
        CommandsFileV3.model_validate(data)


def test_unknown_state_is_not_empty_and_holding_cannot_switch():
    setup = CommandsFileV3.model_validate(example()).robot_setup
    for known, held, error in [(False, None, "state_unknown"), (True, 7, "holding_object")]:
        state = RobotRuntimeState(arms={"left": {"state_known": known, "holding_object": held},
                                       "right": {"state_known": True}})
        with pytest.raises(ValueError, match=error):
            state.require_idle(setup)
    RobotRuntimeState(arms={"left": {"state_known": True}, "right": {"state_known": True}}).require_idle(setup)

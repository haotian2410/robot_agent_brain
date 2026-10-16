import copy

import pytest

from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
from robot_agent_brain.contracts.robot_setup import RobotRuntimeState
from robot_agent_brain.planning.coordinated_validator import CoordinatedValidator
from test_dual_commands_contract import example


def runtime(left=None, right=None):
    return RobotRuntimeState(arms={side: {"state_known": True, "holding_object": held}
                                   for side, held in (("left", left), ("right", right))})


def plan(stages):
    data = example()
    data["operations"] = [{"operation_id": side, "semantic_intent": "fixture",
                           "task_type": "pick_and_place", "arm": side}
                          for side in ("left", "right") if any(side in stage for stage in stages)]
    data["steps"] = []
    for i, stage in enumerate(stages):
        slots = {"left": None, "right": None}
        for side, (skill, params) in stage.items():
            slots[side] = {"command_id": f"cmd-{i}-{side}", "source_skill_step_id": f"skill-{i}-{side}",
                           "operation_id": side, "skill_name": skill, "parameters": params}
        data["steps"].append({"step_id": str(i), "semantic_intent": "fixture", "arms": slots})
    return CommandsFileV3.model_validate(data)


def test_parallel_pick_place_and_null_holding_are_symbolic_only():
    stages = []
    for skill, region in [("locate", None), ("move", "grasp_region"), ("grasp", None),
                          ("locate", None), ("move", "placement_region"), ("release", "placement_region")]:
        stage = {}
        for side, obj, box in [("left", 7, 9), ("right", 8, 10)]:
            target = box if len(stages) in (3, 4) else obj
            params = {"target": target}
            if region:
                params["region"] = region
            if skill == "release":
                params["reference"] = box
            stage[side] = (skill, params)
        stages.append(stage)
    initial = runtime()
    original = copy.deepcopy(initial)
    result = CoordinatedValidator().validate(plan(stages), initial)
    assert result.holding == {"left": None, "right": None}
    assert initial == original
    result = CoordinatedValidator().validate(plan([{"left": ("locate", {"target": 7})}]), runtime(right=8))
    assert result.holding["right"] == 8


def test_same_stage_does_not_share_new_locate_effect():
    candidate = plan([{"left": ("locate", {"target": 7}),
                       "right": ("move", {"target": 7, "region": "grasp_region"})}])
    with pytest.raises(ValueError, match="requires_located"):
        CoordinatedValidator().validate(candidate, runtime())


def test_two_arms_grasping_same_object_conflicts():
    stages = [{side: ("locate", {"target": 7}) for side in ("left", "right")},
              {side: ("move", {"target": 7, "region": "grasp_region"}) for side in ("left", "right")},
              {side: ("grasp", {"target": 7}) for side in ("left", "right")}]
    with pytest.raises(ValueError, match="resource_conflict"):
        CoordinatedValidator().validate(plan(stages), runtime())


def test_move_invalidates_located_fact_and_unknown_state_rejected():
    candidate = plan([{"left": ("locate", {"target": 7})},
                      {"left": ("move", {"target": 7, "motion_direction": "right", "distance_m": .1})}])
    result = CoordinatedValidator().validate(candidate, runtime(left=7))
    assert 7 not in result.located
    initial = runtime()
    initial.arms["right"].state_known = False
    with pytest.raises(ValueError, match="state_unknown"):
        CoordinatedValidator().validate(candidate, initial)

import pytest

from robot_agent_brain.contracts.commands_v3 import CommandsFileV3
from robot_agent_brain.planning.coordinated_validator import CoordinatedValidator
from test_coordinated_validator import plan, runtime


def hold_plan():
    value = plan([
        {"right": ("locate", {"target": 8})},
        {"right": ("move", {"target": 8, "region": "grasp_region"})},
        {"right": ("grasp", {"target": 8})},
    ]).model_dump()
    value["hold_constraints"] = [{"kind": "hold_during_operation", "holder_arm": "left",
                                  "object_id": 7, "while_operation": "right"}]
    return CommandsFileV3.model_validate(value)


def test_explicit_null_hold_has_machine_readable_invariants():
    from robot_agent_brain.planning.dual_condition_builder import build_conditions
    candidate = build_conditions(hold_plan(), runtime(left=7))
    for stage in candidate.steps:
        assert stage.arms.left is None
        assert {"predicate": "holding", "arm": "left", "object_id": 7} in [c.model_dump() for c in stage.invariants]
    assert CoordinatedValidator().validate(candidate, runtime(left=7)).holding == {"left": 7, "right": 8}


def test_missing_required_hold_invariant_fails_closed():
    from robot_agent_brain.planning.dual_condition_builder import build_conditions
    candidate = build_conditions(hold_plan(), runtime(left=7))
    candidate.steps[1].invariants = []
    with pytest.raises(ValueError, match="required_invariant_missing"):
        CoordinatedValidator().validate(candidate, runtime(left=7))


def test_missing_action_preconditions_fails_closed():
    from robot_agent_brain.planning.dual_condition_builder import build_conditions
    candidate = build_conditions(hold_plan(), runtime(left=7))
    candidate.steps[2].preconditions = []
    with pytest.raises(ValueError, match="required_precondition_missing"):
        CoordinatedValidator().validate(candidate, runtime(left=7))


def test_hold_requires_proven_initial_ownership():
    from robot_agent_brain.planning.dual_condition_builder import build_conditions
    candidate = build_conditions(hold_plan(), runtime())
    with pytest.raises(ValueError, match="condition_unproven"):
        CoordinatedValidator().validate(candidate, runtime())


@pytest.mark.parametrize("mode", ["recipe", "qwen"])
def test_semantic_hold_constraint_survives_parse_grounding_and_planner(mode):
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    from test_dual_session_pipeline import configured
    from test_dual_qwen_planner import Provider, output
    session, _ = configured(mode)
    session.arm_states.arms["left"].holding_object = 7
    if mode == "qwen":
        session.pipeline.skill_planner.provider = Provider(output())
    turn = TaskParseOutput.model_validate({
        "entities": [{"id": "apple", "name": "apple", "category": "fruit"},
                     {"id": "banana", "name": "banana", "category": "fruit"}],
        "operations": [{"type": "grasp", "target": "banana", "arm": "right"}],
        "hold_constraints": [{"kind": "hold_during_operation", "holder_arm": "left",
                              "object_entity": "apple", "while_operation": "op-1"}],
    }).to_brain_turn("左臂保持苹果，右臂抓香蕉")
    result = session.process_turn("hold", turn)
    assert result.commands.hold_constraints[0].object_id == 7
    assert all(any(c.predicate == "holding" and c.arm == "left" and c.object_id == 7
                   for c in stage.invariants) for stage in result.commands.steps)


def test_explicit_hold_cannot_move_held_object_during_peer_operation():
    from robot_agent_brain.planning.dual_condition_builder import build_conditions
    value = hold_plan().model_dump()
    value["operations"].append({"operation_id": "left", "semantic_intent": "move", "task_type": "move", "arm": "left", "target": 7, "parallel_group": "fixture"})
    value["steps"][1]["arms"]["left"] = {
        "command_id": "left-move", "source_skill_step_id": "left-move", "operation_id": "left", "skill_name": "move",
        "parameters": {"target": 7, "motion_direction": "right", "distance_m": .1},
    }
    candidate = build_conditions(CommandsFileV3.model_validate(value), runtime(left=7))
    with pytest.raises(ValueError, match="invariant_conflict"):
        CoordinatedValidator().validate(candidate, runtime(left=7))


def milestone_task():
    from test_dual_recipe import task_scene
    from robot_agent_brain.contracts.grounded_task import GroundedTask
    task, scene = task_scene("pick_and_place", parallel=False)
    data = task.model_dump()
    data["operations"][1] = {"operation_id": "op-2", "task_type": "move", "target": "banana",
                              "arm": "right", "motion_direction": "right", "distance_m": .1}
    data["hold_constraints"] = [{"kind": "hold_until_operation", "holder_arm": "left",
        "holder_operation": "op-1", "object_entity": "apple", "region_entity": "box",
        "region": "placement_region", "while_operation": "op-2"}]
    return GroundedTask.model_validate(data), scene


def test_recipe_schedules_placement_then_peer_then_release():
    from robot_agent_brain.planning.dual_arm_recipe_planner import DualArmRecipePlanner
    from robot_agent_brain.planning.task_expander import TaskExpander
    from test_dual_commands_contract import example
    task, scene = milestone_task()
    task = TaskExpander().expand(task, scene)
    setup = CommandsFileV3.model_validate(example()).robot_setup
    commands = DualArmRecipePlanner().plan("milestone", task, scene, setup, 1, runtime())
    assert_milestone(commands)


def assert_milestone(commands):
    ready = next(i for i, s in enumerate(commands.steps) if s.arms.left is not None
                 and s.arms.left.skill_name == "move" and s.arms.left.parameters.region == "placement_region")
    release = next(i for i, s in enumerate(commands.steps) if s.arms.left is not None and s.arms.left.skill_name == "release")
    peer = [i for i, s in enumerate(commands.steps) if s.arms.right is not None]
    assert ready < min(peer) <= max(peer) < release
    for i in peer:
        assert commands.steps[i].arms.left is None
        assert {c.predicate for c in commands.steps[i].invariants} >= {"holding", "at_region"}
    assert CoordinatedValidator().validate(commands, runtime()).holding == {"left": None, "right": None}


def milestone_model_output():
    left = [{"operation_id": "op-1", "skill": skill, "target_role": target,
             "reference_role": reference, "region": region} for skill, target, reference, region in (
        ("locate", "source", None, None), ("move", "source", None, "grasp_region"),
        ("grasp", "source", None, None), ("locate", "destination", None, None),
        ("move", "destination", "source", "placement_region"),
        ("release", "source", "destination", "placement_region"))]
    right = [{"operation_id": "op-2", "skill": skill, "target_role": "target", "region": region}
             for skill, region in (("locate", None), ("move", "grasp_region"), ("grasp", None),
                                   ("move", None), ("release", None))]
    return {"stages": ([{"left": a, "right": None} for a in left[:-1]]
                       + [{"left": None, "right": a} for a in right]
                       + [{"left": left[-1], "right": None}])}


@pytest.mark.parametrize("bad", [None, "early_release", "same_stage_ready"])
def test_qwen_milestone_order_is_checked_not_repaired(bad):
    from test_dual_qwen_planner import Provider
    from test_dual_session_pipeline import configured
    from robot_agent_brain.planning.dual_qwen_planner import DualQwenPlanner
    from robot_agent_brain.planning.skill_planner_router import PlanningTrace
    from robot_agent_brain.skills.registry import REGISTRY
    task, scene = milestone_task()
    _, registry = configured()
    data = milestone_model_output()
    if bad == "early_release":
        data["stages"].insert(5, data["stages"].pop())
    elif bad == "same_stage_ready":
        data["stages"][4]["right"] = data["stages"].pop(5)["right"]
    provider = Provider(data)
    def run():
        return DualQwenPlanner().plan("q", task, scene, registry.profiles["fixture_only"],
            1, runtime(), provider, REGISTRY, PlanningTrace("qwen"))
    if bad:
        with pytest.raises(ValueError, match="milestone_order_invalid|unrequested_parallel"):
            run()
    else:
        assert_milestone(run())
    assert len(provider.calls) == 1


def test_explicit_whole_operation_dependency_not_deleted_by_milestone():
    from robot_agent_brain.planning.task_expander import TaskExpander
    from robot_agent_brain.planning.dual_arm_recipe_planner import DualArmRecipePlanner
    from test_dual_commands_contract import example
    task, scene = milestone_task()
    task.operations[1].depends_on = ["op-1"]
    task = TaskExpander().expand(task, scene)
    assert task.operations[1].depends_on == ["op-1"]
    with pytest.raises(ValueError, match="dependency_cycle"):
        DualArmRecipePlanner().plan("cycle", task, scene, CommandsFileV3.model_validate(example()).robot_setup, 1, runtime())


def test_model_cannot_drop_explicit_hold_until_semantics():
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    value = {"entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
             "operations": [{"type": "grasp", "target": "apple", "arm": "left"}]}
    with pytest.raises(ValueError, match="hold_constraint_required"):
        TaskParseOutput.model_validate(value).to_task_intent("左臂保持苹果，右臂操作，然后左臂再松手")


def test_holder_waits_through_peer_move_and_subsequent_placement():
    from robot_agent_brain.contracts.task_intent import Operation
    from robot_agent_brain.planning.task_expander import TaskExpander
    from robot_agent_brain.planning.dual_arm_recipe_planner import DualArmRecipePlanner
    from test_dual_commands_contract import example
    task, scene = milestone_task()
    task.operations.append(Operation(operation_id="op-3", task_type="pick_and_place",
        arm="right", source="banana", destination="box",
        placement_target={"kind": "container_interior", "reference": "box"}, depends_on=["op-2"]))
    task.hold_constraints.append(task.hold_constraints[0].model_copy(update={"while_operation": "op-3"}))
    task = TaskExpander().expand(task, scene)
    commands = DualArmRecipePlanner().plan("move-then-place", task, scene,
        CommandsFileV3.model_validate(example()).robot_setup, 1, runtime())
    assert_milestone(commands)
    right = [s.arms.right for s in commands.steps if s.arms.right is not None]
    assert right[-1].skill_name == "release"
    assert right[-1].parameters.reference == 9
    assert [a.operation_id for a in right] == ["op-2"] * 5 + ["op-3"] * 6

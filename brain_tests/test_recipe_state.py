import pytest
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.planning.recipe_planner import RecipePlanner


def task(operations):
    return GroundedTask(instruction="test", scene_id="s", scene_version=0,
                        entities=[GroundedEntity(entity_id=name, semantic_name="apple", scene_object_id=name+"_01",
                                                  asset_id="apple", category="fruit") for name in ("a", "b")],
                        operations=operations)


def move():
    return Operation(operation_id="op-2", task_type="move", target="a", motion_direction="right", distance_m=.1)


def test_compound_grasp_move_release_once():
    value = task([Operation(operation_id="op-1", task_type="grasp", target="a"), move(),
                  Operation(operation_id="op-3", task_type="release", target="a")])
    steps = RecipePlanner().plan(value).steps
    assert [s.skill_name.value for s in steps] == ["locate", "move", "grasp", "move", "release"]
    assert {s.operation_id for s in steps} == {"op-1", "op-2", "op-3"}


def test_standalone_move_still_grasps_and_releases():
    assert [s.skill_name.value for s in RecipePlanner().plan(task([move()])).steps] == ["locate", "move", "grasp", "move", "release"]


def test_double_grasp_blocked_not_silently_rewritten():
    for target in ("a", "b"):
        with pytest.raises(ValueError, match="holding_conflict"):
            RecipePlanner().plan(task([Operation(operation_id="op-1", task_type="grasp", target="a"),
                                        Operation(operation_id="op-2", task_type="grasp", target=target)]))


def test_release_requires_matching_confirmed_holding():
    value = task([Operation(operation_id="op-1", task_type="release", target="a")])
    for held in (None, "b_01"):
        with pytest.raises(ValueError, match="plan_precondition_failed"):
            RecipePlanner().plan(value, held_object=held)
    assert len(RecipePlanner().plan(value, held_object="a_01").steps) == 1


def test_search_is_not_locate():
    with pytest.raises(ValueError, match="capability_unsupported"):
        RecipePlanner().plan(task([Operation(operation_id="op-1", task_type="search", target="a")]))

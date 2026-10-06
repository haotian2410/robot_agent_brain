import pytest
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.planning.plan_validator import PlanValidator
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from test_recipe_state import task, move


def scene():
    return SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id=name+"_01", semantic_name="apple",
                        asset_id="apple", category="fruit") for name in ("a", "b")])


def test_valid_compound_and_initial_holding():
    value = task([Operation(operation_id="op-1", task_type="grasp", target="a"), move(),
                  Operation(operation_id="op-3", task_type="release", target="a")])
    PlanValidator().validate(value, RecipePlanner().plan(value), scene())
    value = task([move()])
    PlanValidator().validate(value, RecipePlanner().plan(value, held_object="a_01"), scene(), held_object="a_01")


@pytest.mark.parametrize("mutation", ["missing_effect", "missing_locate", "wrong_role", "duplicate_id", "dependency", "missing_instance", "extra_move"])
def test_invalid_plan_rejected_independently_of_planner(mutation):
    value = task([move()])
    plan = RecipePlanner().plan(value)
    current_scene = scene()
    if mutation == "missing_effect":
        plan.steps.pop()
    elif mutation == "missing_locate":
        plan.steps.pop(0)
    elif mutation == "wrong_role":
        plan.steps[3].target_entity = "b"
    elif mutation == "duplicate_id":
        plan.steps[1].step_id = plan.steps[0].step_id
    elif mutation == "dependency":
        value.operations[0].depends_on = ["unknown"]
    elif mutation == "missing_instance":
        current_scene.objects = []
    elif mutation == "extra_move":
        plan.steps.insert(4, plan.steps[3].model_copy(update={"step_id":"extra"}))
    with pytest.raises(ValueError, match="plan_precondition_failed"):
        PlanValidator().validate(value, plan, current_scene)


def test_placement_role_cannot_swap_source_and_destination():
    value = task([Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                           placement_target={"kind":"relative_object", "reference":"b", "relation":"near"})])
    plan = RecipePlanner().plan(value)
    PlanValidator().validate(value, plan, scene())
    plan.steps[-1].reference_entity = "a"
    with pytest.raises(ValueError, match="release placement mismatch"):
        PlanValidator().validate(value, plan, scene())

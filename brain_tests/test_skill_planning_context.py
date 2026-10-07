import json

from robot_agent_brain.contracts.task_intent import Operation, SpatialRelation
from robot_agent_brain.planning.context_builder import build_planner_context
from robot_agent_brain.skills.registry import REGISTRY
from test_recipe_state import task, move


def placement_task():
    value = task([Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                            placement_target={"kind": "relative_object", "reference": "b", "relation": "near"})])
    value.spatial_relations = [SpatialRelation(scope="goal", subject="a", relation="near", reference="b")]
    return value


def test_context_roles_goals_and_physical_projection():
    value = placement_task()
    context = build_planner_context(value, "a_01")
    op = context.operations[0]
    assert op.id == "op-1" and op.valid_roles == ("source", "destination")
    assert op.role_bindings.source == "a" and op.role_bindings.destination == "b"
    assert context.initial_state.held_entity == "a" and context.initial_state.gripper_occupied
    assert context.goals[0].reference == "b"
    assert "source=a" in context.semantic_summary
    payload = context.model_dump_json()
    for forbidden in ("scene_object_id", "asset_id", "position", "quaternion", "scale", "bbox", "joint",
                      "trajectory", "ik", "collision", "path", "mesh", "a_01", "b_01", "distance_m"):
        assert forbidden not in payload
    assert {e.id for e in context.entities} == {"a", "b"}


def test_context_external_holding_and_order():
    value = task([Operation(operation_id="op-1", task_type="grasp", target="a"),
                  move().model_copy(update={"depends_on": ["op-1"]})])
    context = build_planner_context(value, "unrelated_01")
    assert context.initial_state.held_entity is None and context.initial_state.gripper_occupied
    assert [op.id for op in context.operations] == ["op-1", "op-2"]
    assert context.operations[1].depends_on == ["op-1"]
    assert context.operations[1].motion_direction == "right"
    assert "distance_m" not in context.model_dump_json()


def test_atomic_catalog_is_self_contained_not_recipes():
    definitions = [json.loads(line) for line in REGISTRY.prompt_catalog().splitlines()]
    assert {d["name"] for d in definitions} == {"locate", "move", "grasp", "release", "press", "pull", "push"}
    assert all(d["description"] and d["prompt_signature"] and d["effects"] for d in definitions)
    assert "pick_and_place" not in REGISTRY.prompt_catalog()

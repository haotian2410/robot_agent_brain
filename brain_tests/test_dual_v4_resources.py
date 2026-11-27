import pytest
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.planning.dual_v4_planner import plan_v4
from robot_agent_brain.planning.skill_planner_router import PlanningTrace
from test_dual_v4_pipeline import setup
from test_component_runtime import object_


def shared_destination():
    session = setup()
    session.scene.objects.append(object_(9, "basket", "container"))
    task = GroundedTask(instruction="分别放进篮子", scene_id=session.scene.scene_id,
        scene_version=session.scene.scene_version,
        entities=[{"entity_id": name, "semantic_name": name, "category": category, "scene_object_id": identifier}
                  for name, category, identifier in [("apple", "fruit", 7), ("banana", "fruit", 8), ("basket", "container", 9)]],
        operations=[{"operation_id": f"op-{index}", "task_type": "pick_and_place",
                     "source": source, "destination": "basket", "arm": arm,
                     "placement_target": {"kind": "container_interior", "reference": "basket"}}
                    for index, source, arm in [(1, "apple", "left"), (2, "banana", "right")]])
    contract = session.pipeline.control_skill_contract
    contract["skills"]["put"] = {"expansion_level": "task",
        "object_parameters": {"destination": "destination_object_id"},
        "parameters_schema": {"type": "object", "properties": {"destination": {"type": "integer"}, "placement": {"type": "object"}},
                              "required": ["destination"], "additionalProperties": False}}
    contract["operation_semantics"]["pick_and_place"] = {
        "required_skill_sequence": ["pick", "put"],
        "parameter_bindings": {"put": {"placement": "placement_target"}}}
    def recipe(request):
        return {"operations": [{"operation_id": op.operation_id, "steps": [
            {"skill_name": "pick", "parameters": {"source": op.source_object_id}},
            {"skill_name": "put", "parameters": {"destination": op.destination_object_id, "placement": {"kind": "container_interior", "reference": op.destination_object_id}}}]}
            for op in request.operations]}
    return plan_v4(request_id="shared", task=task, scene=session.scene,
        profile=session.robot_profiles.profiles["fixture_only"], revision=session.robot_setup_revision,
        runtime=session.arm_states, skill_contract=contract, provider=None, recipe=recipe,
        trace=PlanningTrace("recipe", used_planner="recipe"))


def test_same_container_has_no_shared_metadata_or_cross_arm_order():
    result = shared_destination()
    assert result.schema_version == "4.1"
    assert not {"resource_groups", "hold_constraints", "sync_groups", "execution_policy"} & result.model_dump().keys()
    assert [command.depends_on for command in result.commands] == [
        [], ["L-op-1-1"], [], ["R-op-2-1"]]

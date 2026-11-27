import pytest
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.planning.dual_v4_planner import plan_v4
from robot_agent_brain.planning.skill_planner_router import PlanningTrace
from test_dual_v4_pipeline import setup
from test_component_runtime import object_


def shared_destination(*, simultaneous=False, supports_resources=True, supports_sync=True):
    session = setup()
    session.scene.objects.append(object_(9, "basket", "container"))
    task = GroundedTask(instruction="分别放进篮子", scene_id=session.scene.scene_id,
        scene_version=session.scene.scene_version,
        entities=[{"entity_id": name, "semantic_name": name, "category": category, "scene_object_id": identifier}
                  for name, category, identifier in [("apple", "fruit", 7), ("banana", "fruit", 8), ("basket", "container", 9)]],
        operations=[{"operation_id": f"op-{index}", "task_type": "pick_and_place",
                     "source": source, "destination": "basket", "arm": arm,
                     "placement_target": {"kind": "container_interior", "reference": "basket"},
                     "parallel_group": "start-together" if simultaneous else None,
                     "parallel_required": simultaneous}
                    for index, source, arm in [(1, "apple", "left"), (2, "banana", "right")]])
    contract = session.pipeline.control_skill_contract
    contract.update(supports_resources=supports_resources, supports_sync=supports_sync)
    contract["skills"]["put"] = {"expansion_level": "task",
        "object_parameters": {"destination": "destination_object_id"},
        "parameters_schema": {"type": "object", "properties": {"destination": {"type": "integer"}},
                              "required": ["destination"], "additionalProperties": False}}
    def recipe(request):
        return {"operations": [{"operation_id": op.operation_id, "steps": [
            {"skill_name": "pick", "parameters": {"source": op.source_object_id}},
            {"skill_name": "put", "parameters": {"destination": op.destination_object_id}}]}
            for op in request.operations]}
    return plan_v4(request_id="shared", task=task, scene=session.scene,
        profile=session.robot_profiles.profiles["fixture_only"], revision=session.robot_setup_revision,
        runtime=session.arm_states, skill_contract=contract, provider=None, recipe=recipe,
        trace=PlanningTrace("recipe", used_planner="recipe"))


def test_same_container_declares_placement_resource_without_cross_arm_order():
    result = shared_destination()
    assert not result.sync_groups
    assert len(result.resource_groups) == 1
    group = result.resource_groups[0]
    assert group.resource_id == "object:9:placement"
    assert group.command_ids == ["L-op-1-2", "R-op-2-2"]
    assert result.commands[0].depends_on == result.commands[2].depends_on == []


def test_explicit_simultaneous_start_only_synchronizes_operation_starts():
    result = shared_destination(simultaneous=True)
    assert result.sync_groups[0].command_ids == ["L-op-1-1", "R-op-2-1"]


@pytest.mark.parametrize("options,field", [
    ({"supports_resources": False}, "resource_groups"),
    ({"simultaneous": True, "supports_sync": False}, "sync_groups"),
])
def test_unadvertised_features_are_not_ignored(options, field):
    with pytest.raises(ValueError, match="control_dag_feature_unsupported: " + field):
        shared_destination(**options)

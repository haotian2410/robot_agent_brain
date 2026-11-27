import pytest

from robot_agent_brain.contracts.commands_v3 import CommandsFileV3, canonical_commands_v3
from robot_agent_brain.contracts.grounded_task import GroundedTask
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.planning.dual_arm_recipe_planner import DualArmRecipePlanner
from test_component_runtime import object_
from test_dual_commands_contract import example
from test_coordinated_validator import runtime


def task_scene(kind="grasp", parallel=True):
    entities = [{"entity_id": name, "semantic_name": name, "category": category, "scene_object_id": i}
                for i, name, category in [(7, "apple", "fruit"), (8, "banana", "fruit"), (9, "box", "container")]]
    operations = []
    for i, (side, actor) in enumerate((("left", "apple"), ("right", "banana")), 1):
        params = {"source": actor, "destination": "box", "placement_target": {"kind": "container_interior", "reference": "box"}} if kind == "pick_and_place" else {"target": actor}
        if kind == "move":
            params.update(motion_direction="right", distance_m=.1)
        operations.append(Operation(operation_id=f"op-{i}", task_type=kind, arm=side,
                                    **params))
    task = GroundedTask(instruction="fixture", scene_id=1, scene_version=0, entities=entities, operations=operations)
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="fixture",
                        objects=[object_(e.scene_object_id, e.semantic_name, e.category) for e in task.entities])
    return task, scene


@pytest.mark.parametrize("kind", ["grasp", "move", "pick_and_place"])
def test_retired_staged_recipe_rejects_old_callers(kind):
    task, scene = task_scene(kind)
    setup = CommandsFileV3.model_validate(example()).robot_setup
    with pytest.raises(ValueError, match="staged_dual_v3_retired"):
        DualArmRecipePlanner().plan("fixture", task, scene, setup, 1, runtime())


def test_v41_recipe_must_cover_every_operation_without_inventing_stages():
    from test_dual_v4_pipeline import setup
    from test_dual_coordinated_capability import task
    session = setup()
    session.pipeline.dual_skill_recipe = lambda request: {"operations": [
        {"operation_id": "op-1", "steps": [{"skill_name": "pick", "parameters": {"source": 7}}]}]}
    with pytest.raises(ValueError, match="operation_coverage_invalid"):
        session.process_turn("missing", task())
    assert not session.exported_commands


def test_v41_recipe_rejects_unregistered_skill_without_fallback():
    from test_dual_v4_pipeline import setup
    from test_dual_session_pipeline import task
    session = setup()
    session.pipeline.dual_skill_recipe = lambda request: {"operations": [
        {"operation_id": "op-1", "steps": [{"skill_name": "unregistered", "parameters": {}}]}]}
    with pytest.raises(ValueError, match="control_skill_unregistered"):
        session.process_turn("unknown", task())
    assert not session.exported_commands

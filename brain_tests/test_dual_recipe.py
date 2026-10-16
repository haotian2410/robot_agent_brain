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
                                    parallel_group="g" if parallel else None, parallel_required=parallel, **params))
    task = GroundedTask(instruction="fixture", scene_id=1, scene_version=0, entities=entities, operations=operations)
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="fixture",
                        objects=[object_(e.scene_object_id, e.semantic_name, e.category) for e in task.entities])
    return task, scene


@pytest.mark.parametrize("kind,count", [("grasp", 3), ("move", 5), ("pick_and_place", 6)])
def test_dual_recipe_existing_skills_roundtrip(kind, count):
    task, scene = task_scene(kind)
    setup = CommandsFileV3.model_validate(example()).robot_setup
    commands = DualArmRecipePlanner().plan("fixture", task, scene, setup, 1, runtime())
    assert len(commands.steps) == count
    assert all(s.arms.left is not None and s.arms.right is not None for s in commands.steps)
    assert CommandsFileV3.model_validate(canonical_commands_v3(commands)) == commands


def test_sequential_recipe_keeps_explicit_null_slots():
    task, scene = task_scene(parallel=False)
    setup = CommandsFileV3.model_validate(example()).robot_setup
    commands = DualArmRecipePlanner().plan("fixture", task, scene, setup, 1, runtime())
    assert len(commands.steps) == 6
    assert all(s.arms.right is None for s in commands.steps[:3])
    assert all(s.arms.left is None for s in commands.steps[3:])


def test_parallel_same_arm_is_not_silently_serialized():
    task, scene = task_scene()
    task.operations[1].arm = "left"
    setup = CommandsFileV3.model_validate(example()).robot_setup
    with pytest.raises(ValueError, match="parallel_arm_conflict"):
        DualArmRecipePlanner().plan("fixture", task, scene, setup, 1, runtime())

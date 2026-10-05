from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.task_intent import Direction, Operation, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.pipeline import BrainPipeline


class MoveUnderstanding:
    def understand_turn(self, request):
        task = TaskIntent(
            instruction=request.instruction,
            entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit"),
                      TaskEntity(entity_id="banana", semantic_name="banana", category="fruit")],
            operations=[
                Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, distance_m=.05),
                Operation(operation_id="op-2", task_type=TaskType.MOVE, target="banana", motion_direction=Direction.FRONT, distance_m=.1),
            ],
        )
        return BrainTurn(status="accepted", turn_kind="robot_task", instruction=request.instruction, task_intent=task)


def test_multiple_scene_moves_are_atomic_and_keep_transform_components():
    assets = LocalAssetCatalog([
        ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1, .1, .1)),
        ModelProperty(asset_id="banana", semantic_name="banana", category="fruit", dimensions_m=(.1, .1, .1)),
    ])
    scene = SceneConfig(scene_id="s", objects=[
        SceneObject(scene_object_id="apple_01", asset_id="apple", semantic_name="apple", category="fruit",
                    transform=Transform(quaternion_xyzw=(0, 0, .707, .707), scale=(2, 1, 1))),
        SceneObject(scene_object_id="banana_01", asset_id="banana", semantic_name="banana", category="fruit",
                    transform=Transform(position=(.4, 0, 0))),
    ])
    result = BrainPipeline(MoveUnderstanding(), assets).run("r", "苹果向右移动，香蕉向前移动", scene)
    assert result.commands is None
    assert len(result.scene_patch.operations) == 2
    assert result.scene_patch.operations[0].transform.position == (.05, 0, 0)
    assert result.scene_patch.operations[0].transform.quaternion_xyzw == (0, 0, .707, .707)
    assert result.scene_patch.operations[0].transform.scale == (2, 1, 1)

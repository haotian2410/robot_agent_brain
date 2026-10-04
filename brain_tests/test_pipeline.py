from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.pipeline import BrainPipeline


class FakeUnderstanding:
    def understand(self, request):
        return TaskIntent(
            instruction=request.instruction,
            entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")],
            operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, motion_scale=MotionScale.SMALL)],
        )


def test_end_to_end_brain_pipeline_without_physics():
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple_basic", semantic_name="apple", category="fruit", dimensions_m=(0.08, 0.08, 0.09))])
    scene = SceneConfig(scene_id="scene-001", scene_version=4, robot="ur5e", objects=[
        SceneObject(scene_object_id="apple_01", asset_id="apple_basic", semantic_name="apple", category="fruit"),
    ])
    result = BrainPipeline(FakeUnderstanding(), assets).run("req-001", "把苹果向右移动一点", scene)
    assert result.commands is None
    patch = result.scene_patch.operations[0]
    assert patch.transform.position == (0.008, 0.0, 0.0)

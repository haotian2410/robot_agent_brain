from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.config import BrainConfig
from test_component_runtime import object_


class FakeUnderstanding:
    def understand(self, request):
        return TaskIntent(
            instruction=request.instruction,
            entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")],
            operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, motion_scale=MotionScale.SMALL)],
        )


def test_end_to_end_brain_pipeline_without_physics():
    assets = BrainConfig().load_assets()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=4, scene_name="scene-001",
                        objects=[object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2")])
    result = BrainPipeline(FakeUnderstanding(), assets).run("req-001", "把苹果向右移动一点", scene)
    assert result.commands is None
    patch = result.scene_patch.operations[0]
    assert patch.component.properties["position"] == [0.008, 0.0, 0.0]

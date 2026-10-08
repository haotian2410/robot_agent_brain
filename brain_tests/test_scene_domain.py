from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.task_intent import Direction, Operation, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.config import BrainConfig
from test_component_runtime import object_
import pytest


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
    assets = BrainConfig().load_assets()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=[
        object_(0, "apple", scale=(2, 1, 1), metadata_ref="$DEMO_LIBRARY/2"),
        object_(1, "banana", position=(.4, 0, 0), metadata_ref="$DEMO_LIBRARY/3")])
    scene.objects[0].components[0].properties["quaternion_xyzw"] = [0, 0, 2**-.5, 2**-.5]
    result = BrainPipeline(MoveUnderstanding(), assets).run("r", "苹果向右移动五厘米，香蕉向前移动十厘米", scene)
    assert result.commands is None
    assert len(result.scene_patch.operations) == 4
    assert result.scene_patch.operations[0].component.properties["position"] == [.05, 0, 0]
    assert result.scene_patch.operations[0].component.properties["quaternion_xyzw"] == pytest.approx((0, 0, 2**-.5, 2**-.5))
    assert result.scene_patch.operations[0].component.properties["scale"] == pytest.approx((2, 1, 1))


class NativeSceneUnderstanding:
    def understand_turn(self, request):
        return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                         scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.001, target="target")]))


def test_native_scene_edit_distance_is_replaced_by_text_evidence():
    assets = BrainConfig().load_assets()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=[object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2")])
    result = BrainPipeline(NativeSceneUnderstanding(), assets).run("r", "苹果向右移动十厘米", scene)
    assert result.scene_patch.operations[0].component.properties["position"] == [.1, 0, 0]


def test_native_scene_edit_millimeter_and_vague_scale_evidence():
    assets = BrainConfig().load_assets()
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=[object_(0, "apple", metadata_ref="$DEMO_LIBRARY/2")])
    for text, expected in (("苹果向右移动5毫米", .005), ("苹果向右移动一点", .008)):
        result = BrainPipeline(NativeSceneUnderstanding(), assets).run("r", text, scene)
        assert abs(result.scene_patch.operations[0].component.properties["position"][0] - expected) < 1e-9

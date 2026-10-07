from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.task_intent import Direction, Operation, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan
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
                    transform=Transform(quaternion_xyzw=(0, 0, 2**-.5, 2**-.5), scale=(2, 1, 1))),
        SceneObject(scene_object_id="banana_01", asset_id="banana", semantic_name="banana", category="fruit",
                    transform=Transform(position=(.4, 0, 0))),
    ])
    result = BrainPipeline(MoveUnderstanding(), assets).run("r", "苹果向右移动五厘米，香蕉向前移动十厘米", scene)
    assert result.commands is None
    assert len(result.scene_patch.operations) == 2
    assert result.scene_patch.operations[0].transform.position == (.05, 0, 0)
    assert result.scene_patch.operations[0].transform.quaternion_xyzw == (0, 0, 2**-.5, 2**-.5)
    assert result.scene_patch.operations[0].transform.scale == (2, 1, 1)


class NativeSceneUnderstanding:
    def understand_turn(self, request):
        return BrainTurn(status="accepted", turn_kind="scene_edit", instruction=request.instruction,
                         scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.001, target="target")]))


def test_native_scene_edit_distance_is_replaced_by_text_evidence():
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1, .1, .1))])
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="apple_01", asset_id="apple", semantic_name="apple", category="fruit")])
    result = BrainPipeline(NativeSceneUnderstanding(), assets).run("r", "苹果向右移动十厘米", scene)
    assert result.scene_patch.operations[0].transform.position == (.1, 0, 0)


def test_native_scene_edit_millimeter_and_vague_scale_evidence():
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1, .1, .1))])
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="apple_01", asset_id="apple", semantic_name="apple", category="fruit")])
    for text, expected in (("苹果向右移动5毫米", .005), ("苹果向右移动一点", .01)):
        result = BrainPipeline(NativeSceneUnderstanding(), assets).run("r", text, scene)
        assert abs(result.scene_patch.operations[0].transform.position[0] - expected) < 1e-9

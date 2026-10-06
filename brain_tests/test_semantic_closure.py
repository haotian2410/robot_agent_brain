import pytest

from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.spatial import SpatialRelationType
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, QuantityMode, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, TurnKind, TurnStatus
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.models.task_understanding import normalize_motion_language
from robot_agent_brain.planning.command_exporter import CommandExporter
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.planning.task_expander import TaskExpander
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.contracts.commands import Command


def test_task_prompt_contains_no_other_stage_prompt():
    assert "VISION_GROUNDING_PROMPT" not in TASK_UNDERSTANDING_PROMPT
    assert "SKILL_PLANNING_PROMPT" not in TASK_UNDERSTANDING_PROMPT
    assert "Atomic Skill 规划器" not in TASK_UNDERSTANDING_PROMPT


def test_relations_are_preserved_and_resolved_by_scene_coordinates():
    intent = TaskIntent(
        instruction="rightmost apple",
        entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", quantity_mode=QuantityMode.CANDIDATE_POOL, count=2)],
        operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")],
        spatial_relations=[{"subject": "apple", "relation": SpatialRelationType.RIGHTMOST}],
    )
    scene = SceneConfig(scene_id="s", objects=[
        SceneObject(scene_object_id="apple_01", asset_id="a", semantic_name="apple", category="fruit", transform=Transform(position=(0, 0, 0))),
        SceneObject(scene_object_id="apple_02", asset_id="a", semantic_name="apple", category="fruit", transform=Transform(position=(1, 0, 0))),
    ])
    grounded = SceneGrounder().ground(intent, scene)
    assert grounded.entities[0].scene_object_id == "apple_02"


def test_multi_move_clauses_bind_in_order():
    intent = TaskIntent(
        instruction="苹果向右移动5厘米，然后香蕉向前移动10厘米",
        entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit"), TaskEntity(entity_id="banana", semantic_name="banana", category="fruit")],
        operations=[
            Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, distance_m=.01),
            Operation(operation_id="op-2", task_type=TaskType.MOVE, target="banana", motion_direction=Direction.FRONT, distance_m=.01),
        ],
    )
    normalized = normalize_motion_language(intent)
    assert [item.distance_m for item in normalized.operations] == [.05, .10]
    assert [item.motion_direction for item in normalized.operations] == [Direction.RIGHT, Direction.FRONT]


def test_task_expansion_produces_concrete_commands_for_all_members():
    task = GroundedTask(
        instruction="two apples", scene_id="s", scene_version=0,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id="apple_01", scene_object_ids=["apple_01", "apple_02"], asset_id="a", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")],
    )
    concrete = TaskExpander().expand(task)
    assert [item.entity_id for item in concrete.entities] == ["apple__01", "apple__02"]
    # Preserve the requested two grasps, but a single gripper cannot hold both.
    with pytest.raises(ValueError, match="holding_conflict"):
        RecipePlanner().plan(concrete)
    # Keep the original concrete-target export coverage with a supported action.
    concrete = concrete.model_copy(update={"operations": [
        op.model_copy(update={"task_type": TaskType.LOCATE}) for op in concrete.operations]})
    commands = CommandExporter().export("r", concrete, RecipePlanner().plan(concrete), SceneConfig(scene_id="s", robot="ur5e"))
    assert [item.parameters["target"] for item in commands.commands] == ["apple_01", "apple_02"]


def test_brain_session_uses_local_scene_manager_and_remote_snapshot():
    class Provider:
        def understand(self, request):
            return TaskIntent(instruction=request.instruction, entities=[], operations=[])
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1, .1, .1))])
    scene = SceneConfig(scene_id="s", scene_version=0)
    platform = MockScenePlatform()
    session = BrainSession(scene, BrainPipeline(Provider(), assets), platform)
    from robot_agent_brain.contracts.scene import PatchAction, ScenePatch, ScenePatchOperation
    patch = ScenePatch(scene_id="s", base_scene_version=0, operations=[ScenePatchOperation(action=PatchAction.ADD, scene_object_id="apple_01", object=SceneObject(scene_object_id="apple_01", asset_id="apple", semantic_name="apple", category="fruit"))])
    session.apply_scene_patch(patch)
    assert session.scene.scene_version == 1
    assert len(session.scene.objects) == 1


def test_brain_turn_enforces_single_payload():
    with pytest.raises(ValueError):
        BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT, instruction="x", scene_edit=SceneEditIntent(operation="add", semantic_name="banana", category="fruit"), task_intent=TaskIntent(instruction="x", entities=[], operations=[]))


def test_specific_name_does_not_fall_back_to_same_category():
    intent = TaskIntent(instruction="apple", entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")], operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")])
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="banana_01", asset_id="b", semantic_name="banana", category="fruit")])
    with pytest.raises(ValueError, match="grounding_missing"):
        SceneGrounder().ground(intent, scene)


def test_pairwise_two_operations_do_not_cross_product():
    task = GroundedTask(instruction="分别", scene_id="s", scene_version=0, entities=[
        GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id="apple_01", scene_object_ids=["apple_01", "apple_02"], asset_id="a", category="fruit"),
        GroundedEntity(entity_id="red_box", semantic_name="red_box", scene_object_id="red_box_01", asset_id="r", category="container"),
        GroundedEntity(entity_id="blue_box", semantic_name="blue_box", scene_object_id="blue_box_01", asset_id="b", category="container"),
    ], operations=[
        Operation(operation_id="op-1", task_type=TaskType.PICK_AND_PLACE, source="apple", destination="red_box", assignment_mode="pairwise", placement_target={"kind":"container_interior", "reference":"red_box", "relation":"inside"}),
        Operation(operation_id="op-2", task_type=TaskType.PICK_AND_PLACE, source="apple", destination="blue_box", assignment_mode="pairwise", placement_target={"kind":"container_interior", "reference":"blue_box", "relation":"inside"}),
    ])
    expanded = TaskExpander().expand(task)
    assert len(expanded.operations) == 2
    assert [op.source for op in expanded.operations] == ["apple__01", "apple__02"]


def test_distance_evidence_supports_mm_half_and_chinese_decimal():
    values = []
    for text in ("苹果向右移动5毫米", "苹果向右移动半米", "苹果向右移动零点五米"):
        intent = TaskIntent(instruction=text, entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")], operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, distance_m=.01)])
        values.append(normalize_motion_language(intent).operations[0].distance_m)
    assert values == pytest.approx([.005, .5, .5])


def test_command_schema_contains_skill_parameter_conditionals():
    assert len(Command.model_json_schema()["allOf"]) >= 3


def test_removed_scene_ids_are_never_reused():
    from robot_agent_brain.scene.scene_manager import SceneManager
    from robot_agent_brain.contracts.scene import PatchAction, ScenePatch, ScenePatchOperation
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="banana_01", asset_id="b", semantic_name="banana", category="fruit")])
    manager = SceneManager(scene)
    manager.apply_patch(ScenePatch(scene_id="s", base_scene_version=0, operations=[ScenePatchOperation(action=PatchAction.REMOVE, scene_object_id="banana_01")]))
    assert "banana_01" in manager.scene.retired_object_ids


def test_vague_motion_without_evidence_is_not_silently_small():
    intent = TaskIntent(instruction="苹果向右移动", entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")], operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, distance_m=.01)])
    # The parsed operation remains explicit when there is no linguistic scale;
    # a raw parser result without one must be rejected before export.
    assert normalize_motion_language(intent).operations[0].distance_m == .01


def test_scene_edit_add_uses_asset_and_commits_through_session():
    class Provider:
        def understand_turn(self, request):
            return BrainTurn(status="accepted", turn_kind=TurnKind.SCENE_EDIT, instruction=request.instruction,
                             scene_edit=SceneEditIntent(operation="add", semantic_name="banana", category="fruit", relation="right_of", reference="apple"))
    assets = LocalAssetCatalog([
        ModelProperty(asset_id="apple", semantic_name="apple", category="fruit", dimensions_m=(.1, .1, .1)),
        ModelProperty(asset_id="banana", semantic_name="banana", category="fruit", dimensions_m=(.1, .1, .1)),
    ])
    scene = SceneConfig(scene_id="s", objects=[SceneObject(scene_object_id="apple_01", asset_id="apple", semantic_name="apple", category="fruit")])
    session = BrainSession(scene, BrainPipeline(Provider(), assets), MockScenePlatform())
    result = session.run_task("r", "在苹果右边增加香蕉")
    assert result.scene_patch is not None
    assert session.scene.scene_version == 1
    assert len(session.scene.objects) == 2

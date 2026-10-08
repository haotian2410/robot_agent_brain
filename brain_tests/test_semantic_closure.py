import pytest

from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.spatial import SpatialRelationType
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, QuantityMode, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, TurnKind, TurnStatus, SceneEditPlan
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.models.prompts import TASK_UNDERSTANDING_PROMPT
from robot_agent_brain.models.task_understanding import normalize_motion_language
from robot_agent_brain.planning.command_exporter import CommandExporter
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.planning.task_expander import TaskExpander
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.contracts.commands import Command
from robot_agent_brain.config import BrainConfig
from test_component_runtime import object_
from test_query_scene_continuity import supported_scene


def component_scene(objects=()):
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=list(objects))


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
    scene = component_scene([object_(0, "apple"), object_(1, "apple", position=(1,0,0))])
    grounded = SceneGrounder().ground(intent, scene)
    assert grounded.entities[0].scene_object_id == 1


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
        instruction="two apples", scene_id=1, scene_version=0,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id=0, scene_object_ids=[0, 1], category="fruit")],
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
    commands = CommandExporter(robot="ur5e").export("r", concrete, RecipePlanner().plan(concrete), component_scene([
        object_(e.scene_object_id, e.semantic_name, e.category) for e in concrete.entities]))
    assert [item.parameters["target"] for item in commands.commands] == [0, 1]


def test_brain_session_uses_local_scene_manager_and_remote_snapshot():
    class Provider:
        def understand(self, request):
            return TaskIntent(instruction=request.instruction, entities=[], operations=[])
    assets = BrainConfig().load_assets()
    scene = component_scene()
    platform = MockScenePlatform()
    session = BrainSession(scene, BrainPipeline(Provider(), assets), platform)
    from robot_agent_brain.contracts.scene import PatchAction, ScenePatch, ScenePatchOperation
    patch = ScenePatch(scene_id=1, base_scene_version=0, operations=[ScenePatchOperation(action=PatchAction.ADD, object_id_in_scene=0, object=object_(0, "apple"))])
    session.apply_scene_patch(patch)
    assert session.scene.scene_version == 1
    assert len(session.scene.objects) == 1


def test_brain_turn_enforces_single_payload():
    with pytest.raises(ValueError):
        BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SCENE_EDIT, instruction="x", scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='banana', category='fruit', count=1, quantity_mode='single')], operations=[SceneEditIntent(operation='add', target="target")]), task_intent=TaskIntent(instruction="x", entities=[], operations=[]))


def test_specific_name_does_not_fall_back_to_same_category():
    intent = TaskIntent(instruction="apple", entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")], operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")])
    scene = component_scene([object_(0, "banana")])
    with pytest.raises(ValueError, match="grounding_missing"):
        SceneGrounder().ground(intent, scene)


def test_pairwise_two_operations_do_not_cross_product():
    task = GroundedTask(instruction="分别", scene_id=1, scene_version=0, entities=[
        GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id=0, scene_object_ids=[0, 1], category="fruit"),
        GroundedEntity(entity_id="red_box", semantic_name="red_box", scene_object_id=2, category="container"),
        GroundedEntity(entity_id="blue_box", semantic_name="blue_box", scene_object_id=3, category="container"),
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
    scene = component_scene([object_(0, "banana")])
    manager = SceneManager(scene)
    manager.apply_patch(ScenePatch(scene_id=1, base_scene_version=0, operations=[ScenePatchOperation(action=PatchAction.REMOVE, object_id_in_scene=0)]))
    assert 0 in manager.seen_scene_object_ids
    assert "retired_object_ids" not in manager.scene.model_dump()
    with pytest.raises(ValueError, match="scene_object_id_reused"):
        manager.apply_patch(ScenePatch(scene_id=1, base_scene_version=1, operations=[
            ScenePatchOperation(action=PatchAction.ADD, object_id_in_scene=0, object=object_(0, "banana"))]))


def test_vague_motion_without_evidence_is_not_silently_small():
    intent = TaskIntent(instruction="苹果向右移动", entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit")], operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=Direction.RIGHT, distance_m=.01)])
    # A model-supplied distance is not evidence that the user requested it.
    with pytest.raises(ValueError, match="motion_distance_evidence_missing"):
        normalize_motion_language(intent)


def test_scene_edit_add_uses_asset_and_commits_through_session():
    class Provider:
        def understand_turn(self, request):
            return BrainTurn(status="accepted", turn_kind=TurnKind.SCENE_EDIT, instruction=request.instruction,
                             scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='banana', category='fruit', count=1, quantity_mode='single'), dict(entity_id="reference", semantic_name='apple', category="fruit")], operations=[SceneEditIntent(operation='add', relation='right_of', target="target", reference="reference")]))
    assets = BrainConfig().load_assets()
    scene = supported_scene()
    scene.objects.pop()
    session = BrainSession(scene, BrainPipeline(Provider(), assets), MockScenePlatform())
    result = session.run_task("r", "在苹果右边增加香蕉")
    assert result.scene_patch is not None
    assert session.scene.scene_version == 1
    assert len(session.scene.objects) == 3

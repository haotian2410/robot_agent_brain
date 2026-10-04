import pytest

from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.scene import ModelProperty, SceneConfig, SceneObject
from robot_agent_brain.contracts.skill_plan import SkillName, SkillPlan, SkillStep
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, PlacementTarget, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.planning.command_exporter import CommandExporter
from robot_agent_brain.planning.motion_scale import MotionScaleResolver
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.grounding.scene_grounder import SceneGrounder


def move_task(scale=None, distance=None, direction=Direction.RIGHT):
    return GroundedTask(
        instruction="move apple",
        scene_id="scene",
        scene_version=2,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id="apple_01", asset_id="apple_basic", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=direction, motion_scale=scale, distance_m=distance)],
    )


def test_motion_scale_uses_axis_dimension_and_explicit_distance_wins():
    assets = LocalAssetCatalog([ModelProperty(asset_id="apple_basic", semantic_name="apple", category="fruit", dimensions_m=(0.08, 0.10, 0.12))])
    resolver = MotionScaleResolver(assets)
    assert resolver.resolve(move_task(MotionScale.SMALL)).operations[0].distance_m == pytest.approx(0.008)
    assert resolver.resolve(move_task(MotionScale.MEDIUM, direction=Direction.FRONT)).operations[0].distance_m == pytest.approx(0.05)
    assert resolver.resolve(move_task(MotionScale.LARGE, direction=Direction.UP)).operations[0].distance_m == pytest.approx(0.24)
    explicit = resolver.resolve(move_task(None, 0.2)).operations[0]
    assert explicit.distance_m == pytest.approx(0.2)


def test_missing_model_geometry_is_an_explicit_error():
    assets = LocalAssetCatalog()
    with pytest.raises(ValueError, match="motion_scale_geometry_missing"):
        MotionScaleResolver(assets).resolve(move_task(MotionScale.SMALL))


def test_grasp_commands_have_regions_but_no_physical_pose():
    task = GroundedTask(
        instruction="grasp apple", scene_id="scene", scene_version=0,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id="apple_01", asset_id="apple_basic", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")],
    )
    plan = RecipePlanner().plan(task)
    commands = CommandExporter().export("req-001", task, plan, SceneConfig(scene_id="scene", scene_version=0, robot="ur5e"))
    assert [item.skill_name for item in commands.commands] == ["locate", "move", "grasp"]
    assert commands.commands[1].parameters["region"] == "grasp_region"
    assert all("pose" not in item.parameters and "anchor" not in item.parameters for item in commands.commands)


def test_relative_placement_exports_semantics_without_xyz_or_anchor():
    task = GroundedTask(
        instruction="put baseball near apple", scene_id="scene", scene_version=4,
        entities=[
            GroundedEntity(entity_id="baseball", semantic_name="baseball", scene_object_id="baseball_01", asset_id="baseball_basic", category="ball"),
            GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id="apple_01", asset_id="apple_basic", category="fruit"),
        ],
        operations=[Operation(
            operation_id="op-1", task_type=TaskType.PICK_AND_PLACE, source="baseball", destination="apple",
            placement_target=PlacementTarget(kind="relative_object", reference="apple", relation="near"),
        )],
    )
    commands = CommandExporter().export("req-002", task, RecipePlanner().plan(task), SceneConfig(scene_id="scene", scene_version=4, robot="ur5e"))
    assert commands.operations[0].placement_target.relation == "near"
    assert commands.operations[0].placement_target.reference == "apple_01"
    payload = commands.model_dump_json()
    assert "xyz" not in payload and "anchor" not in payload and "trajectory" not in payload


def test_all_quantity_binds_multiple_scene_members_without_collapsing_count():
    from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
    from robot_agent_brain.contracts.task_intent import QuantityMode
    intent = TaskIntent(
        instruction="put two apples in box",
        entities=[TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", count=2, quantity_mode=QuantityMode.ALL)],
        operations=[],
    )
    scene = SceneConfig(scene_id="scene", objects=[
        SceneObject(scene_object_id="apple_01", asset_id="apple_basic", semantic_name="apple", category="fruit"),
        SceneObject(scene_object_id="apple_02", asset_id="apple_basic", semantic_name="apple", category="fruit"),
    ])
    bound = SceneGrounder().ground(intent, scene)
    assert bound.entities[0].scene_object_ids == ["apple_01", "apple_02"]

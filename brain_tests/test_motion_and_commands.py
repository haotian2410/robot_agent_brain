import pytest

from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject
from robot_agent_brain.contracts.skill_plan import SkillName, SkillPlan, SkillStep
from robot_agent_brain.contracts.task_intent import Direction, MotionScale, Operation, PlacementTarget, TaskEntity, TaskIntent, TaskType
from robot_agent_brain.planning.command_exporter import CommandExporter
from robot_agent_brain.planning.motion_scale import MotionScaleResolver
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.asset_library import AssetGeometry
from test_component_runtime import object_
from test_component_geometry import GeometryResources


def move_task(scale=None, distance=None, direction=Direction.RIGHT):
    return GroundedTask(
        instruction="move apple",
        scene_id=1,
        scene_version=2,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id=0, metadata_ref="test://object", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.MOVE, target="apple", motion_direction=direction, motion_scale=scale, distance_m=distance)],
    )


def test_motion_scale_uses_axis_dimension_and_explicit_distance_wins():
    assets = GeometryResources(AssetGeometry(dimensions_m=(.08,.10,.12), local_aabb_min_m=(-.04,-.05,-.06), local_aabb_max_m=(.04,.05,.06)))
    resolver = MotionScaleResolver(assets)
    assert resolver.resolve(move_task(MotionScale.SMALL)).operations[0].distance_m == pytest.approx(0.008)
    assert resolver.resolve(move_task(MotionScale.MEDIUM, direction=Direction.FRONT)).operations[0].distance_m == pytest.approx(0.05)
    assert resolver.resolve(move_task(MotionScale.LARGE, direction=Direction.UP)).operations[0].distance_m == pytest.approx(0.24)
    explicit = resolver.resolve(move_task(None, 0.2)).operations[0]
    assert explicit.distance_m == pytest.approx(0.2)


def test_missing_model_geometry_is_an_explicit_error():
    assets = BrainConfig().load_assets()
    with pytest.raises(ValueError, match="motion_scale_geometry_missing"):
        MotionScaleResolver(assets).resolve(move_task(MotionScale.SMALL))


def test_grasp_commands_have_regions_but_no_physical_pose():
    task = GroundedTask(
        instruction="grasp apple", scene_id=1, scene_version=0,
        entities=[GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id=0, metadata_ref="test://object", category="fruit")],
        operations=[Operation(operation_id="op-1", task_type=TaskType.GRASP, target="apple")],
    )
    plan = RecipePlanner().plan(task)
    commands = CommandExporter(robot="ur5e").export("req-001", task, plan, SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="scene", objects=[
        object_(0, "apple")]))
    assert [item.skill_name for item in commands.commands] == ["locate", "move", "grasp"]
    assert commands.commands[1].parameters["region"] == "grasp_region"
    assert all("pose" not in item.parameters and "anchor" not in item.parameters for item in commands.commands)


def test_relative_placement_exports_semantics_without_xyz_or_anchor():
    task = GroundedTask(
        instruction="put baseball near apple", scene_id=1, scene_version=4,
        entities=[
            GroundedEntity(entity_id="baseball", semantic_name="baseball", scene_object_id=1, metadata_ref="test://ball", category="ball"),
            GroundedEntity(entity_id="apple", semantic_name="apple", scene_object_id=0, metadata_ref="test://object", category="fruit"),
        ],
        operations=[Operation(
            operation_id="op-1", task_type=TaskType.PICK_AND_PLACE, source="baseball", destination="apple",
            placement_target=PlacementTarget(kind="relative_object", reference="apple", relation="near"),
        )],
    )
    commands = CommandExporter(robot="ur5e").export("req-002", task, RecipePlanner().plan(task), SceneConfig(scene_schema_version=1, scene_id=1, scene_version=4, scene_name="scene", objects=[
        object_(e.scene_object_id, e.semantic_name, e.category) for e in task.entities]))
    assert commands.operations[0].placement_target.relation == "near"
    assert commands.operations[0].placement_target.reference == 0
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
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_name="scene", scene_version=0, objects=[
        object_(0, "apple"),
        object_(1, "apple"),
    ])
    bound = SceneGrounder().ground(intent, scene)
    assert bound.entities[0].scene_object_ids == [0, 1]

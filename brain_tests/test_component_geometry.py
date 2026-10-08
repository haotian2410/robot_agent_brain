"""Geometry tests use measured real-asset cache, not invented centered bounds."""
import json
import math
from pathlib import Path

import pytest

from robot_agent_brain.contracts.asset_library import AssetGeometry
from robot_agent_brain.contracts.grounded_task import GroundedEntity, GroundedTask
from robot_agent_brain.contracts.scene import SceneConfig, TransformProperties
from robot_agent_brain.contracts.task_intent import Operation
from robot_agent_brain.planning.motion_scale import MotionScaleResolver
from robot_agent_brain.scene.geometry import world_bounds, world_corners
from robot_agent_brain.scene.scene_graph import WorldTransform, world_transform
from robot_agent_brain.scene.spatial_facts import SpatialFactResolver
from test_component_runtime import object_


CACHE = json.loads((Path(__file__).parents[1] / "config/brain_asset_geometry_cache.json").read_text())
IDENTITY = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))


def geometry(identifier):
    return AssetGeometry.model_validate(CACHE[str(identifier)])


class GeometryResources:
    """Test AssetLibraryPort resolver with explicitly measured geometry."""
    def __init__(self, model):
        self.model = model
        self.table = AssetGeometry(dimensions_m=(2, 1, .1),
            local_aabb_min_m=(-1, -.5, -.1), local_aabb_max_m=(1, .5, 0))

    def resolve(self, ref):
        return {"test://table": self.table, "test://object": self.model}[ref]


@pytest.mark.parametrize("identifier", [1, 4, 16])
def test_measured_center_bottom_and_xy_offset_support(identifier):
    model = geometry(identifier)
    resources = GeometryResources(model)
    table = object_(0, "table", "surface", position=(0, 0, .8), metadata_ref="test://table")
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="Geometry", objects=[table])
    facts = SpatialFactResolver(resources)
    placed = facts.support_transform(model, table, scene, x=.1, y=.2)
    assert placed.position[2] == pytest.approx(.8 - model.local_aabb_min_m[2])
    low, high = world_bounds(model, placed)
    assert low == pytest.approx((.1 + model.local_aabb_min_m[0], .2 + model.local_aabb_min_m[1], .8))
    assert high[2] == pytest.approx(.8 + model.dimensions_m[2])
    obj = object_(7, "part", "object", position=placed.position, metadata_ref="test://object")
    scene = scene.model_copy(update={"objects": [table, obj]})
    assert facts.infer_support(obj, scene) == 0
    assert facts.footprint_contains(obj, table, scene)
    assert facts.can_evaluate(obj, scene)
    if identifier == 4:
        assert placed.position[2] < .801  # Not height / 2.
    if identifier == 16:
        assert low[1] != pytest.approx(.2 - model.dimensions_m[1] / 2)


def test_bounds_preserve_full_affine_shear_and_offset():
    model = geometry(16)
    affine = WorldTransform((1, 2, 3), ((2, .5, 0), (0, 3, 0), (0, 0, 4)))
    low, high = world_bounds(model, affine)
    assert low == pytest.approx((
        1 + 2 * model.local_aabb_min_m[0] + .5 * model.local_aabb_min_m[1],
        2 + 3 * model.local_aabb_min_m[1], 3 + 4 * model.local_aabb_min_m[2]))
    assert high == pytest.approx((
        1 + 2 * model.local_aabb_max_m[0] + .5 * model.local_aabb_max_m[1],
        2 + 3 * model.local_aabb_max_m[1], 3 + 4 * model.local_aabb_max_m[2]))
    assert len(world_corners(model, affine)) == 8


def test_raw_child_transform_not_accepted_as_world():
    child = TransformProperties(position=(1, 2, 3), quaternion_xyzw=(0, 0, 0, 1), scale=(1, 1, 1), parent=0)
    with pytest.raises(ValueError, match="requires_world_transform"):
        world_bounds(geometry(1), child)


def test_support_uses_world_parent_and_exact_inverse_footprint():
    resources = GeometryResources(geometry(1))
    parent = object_(9, position=(10, 20, .8), scale=(2, 3, 1))
    parent.components[0].properties["quaternion_xyzw"] = [0, 0, math.sqrt(.5), math.sqrt(.5)]
    table = object_(0, "table", "surface", parent=9, metadata_ref="test://table")
    scene = SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="Geometry", objects=[parent, table])
    facts = SpatialFactResolver(resources)
    placed = facts.support_transform(resources.model, table, scene, x=10, y=20)
    obj = object_(7, "apple", "fruit", position=placed.position, metadata_ref="test://object")
    scene = scene.model_copy(update={"objects": [parent, table, obj]})
    assert facts.infer_support(obj, scene) == 0
    assert world_transform(scene, 0).position == (10, 20, .8)
    moved = obj.model_copy(deep=True)
    moved.components[0].properties["position"] = [12, 20, placed.position[2]]
    scene = scene.model_copy(update={"objects": [parent, table, moved]})
    assert not facts.footprint_contains(moved, table, scene)
    assert facts.infer_support(moved, scene) is None


@pytest.mark.parametrize("scale,factor", [("small", .1), ("medium", .5), ("large", 2)])
def test_motion_scale_resolves_metadata_ref_and_measured_size(scale, factor):
    model = geometry(16)
    task = GroundedTask(instruction="往右移动", scene_id=0, scene_version=1,
        entities=[GroundedEntity(entity_id="part", semantic_name="screwdriver",
            scene_object_id=0, metadata_ref="test://object", category="tool", model_scale=(2, 3, 4))],
        operations=[Operation(operation_id="op-1", task_type="move", target="part",
            motion_direction="right", motion_scale=scale)])
    resolved = MotionScaleResolver(GeometryResources(model)).resolve(task)
    assert resolved.operations[0].distance_m == pytest.approx(model.dimensions_m[0] * 2 * factor)
    assert resolved.operations[0].motion_scale is None
    assert task.operations[0].motion_scale == scale

import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import SceneEditIntent, SceneEditPlan
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.layout_geometry import ContainerInteriorGeometry, SceneLayoutGeometryRegistry
from robot_agent_brain.scene.scene_graph import world_transform
from robot_agent_brain.scene.scene_manager import SceneManager
from test_component_runtime import object_
from test_query_scene_continuity import supported_scene


def _entity(identifier, name, category):
    return {"entity_id": identifier, "semantic_name": name, "category": category}


def _scene_with_box():
    scene = supported_scene()
    scene.objects.append(object_(3, "box", "container", position=(.25, .25, .09),
                                 metadata_ref="$DEMO_LIBRARY/5", support=0))
    return scene


def test_back_of_is_normalized_to_behind():
    edit = SceneEditIntent(operation="add", target="b", reference="a", relation="back_of")
    assert edit.relation == "behind"


def test_near_add_uses_aabb_clearance_and_is_atomic():
    config = BrainConfig()
    scene = supported_scene()
    plan = SceneEditPlan(
        entities=[_entity("new", "banana", "fruit"), _entity("ref", "apple", "fruit")],
        operations=[SceneEditIntent(operation="add", target="new", reference="ref", relation="near")],
    )
    result = SceneEditor(config.load_assets()).edit_result(plan, scene)
    changed = SceneManager(scene).apply_patch(result.patch)
    reference = world_transform(changed, 1)
    added = world_transform(changed, result.created_object_ids[0])
    assert abs(added.position[0] - reference.position[0]) > 0 or abs(added.position[1] - reference.position[1]) > 0
    assert changed.scene_version == scene.scene_version + 1


def test_on_add_requires_surface_and_preserves_support():
    config = BrainConfig()
    scene = supported_scene()
    plan = SceneEditPlan(
        entities=[_entity("new", "apple", "fruit"), _entity("ref", "table", "surface")],
        operations=[SceneEditIntent(operation="add", target="new", reference="ref", relation="on")],
    )
    result = SceneEditor(config.load_assets()).edit_result(plan, scene)
    changed = SceneManager(scene).apply_patch(result.patch)
    assert SceneIndex(changed).semantic(result.created_object_ids[0]).support == 0


def test_inside_without_verified_geometry_returns_explicit_error():
    config = BrainConfig()
    scene = _scene_with_box()
    plan = SceneEditPlan(
        entities=[_entity("new", "apple", "fruit"), _entity("ref", "box", "container")],
        operations=[SceneEditIntent(operation="add", target="new", reference="ref", relation="inside")],
    )
    with pytest.raises(ValueError, match="scene_edit_inside_geometry_missing"):
        SceneEditor(config.load_assets()).edit_result(plan, scene)


def test_inside_uses_verified_registry_and_ignores_container_outer_overlap():
    config = BrainConfig()
    scene = _scene_with_box()
    registry = SceneLayoutGeometryRegistry({"model:5": ContainerInteriorGeometry(
        interior_aabb_min_m=(-.09, -.09, -.07), interior_aabb_max_m=(.09, .09, .07),
        floor_z_m=-.07, verified=True, source="fixture")})
    plan = SceneEditPlan(
        entities=[_entity("new", "apple", "fruit"), _entity("ref", "box", "container")],
        operations=[SceneEditIntent(operation="add", target="new", reference="ref", relation="inside")],
    )
    result = SceneEditor(config.load_assets(), layout_interiors=registry).edit_result(plan, scene)
    changed = SceneManager(scene).apply_patch(result.patch)
    assert SceneIndex(changed).semantic(result.created_object_ids[0]).support == 3


def test_unknown_layout_relation_is_not_silently_guessed():
    with pytest.raises(ValueError):
        SceneEditIntent(operation="add", target="a", reference="b", relation="diagonal")

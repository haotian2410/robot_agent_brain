import math
import pytest
from pydantic import ValidationError
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.asset_library import AssetGeometry
from robot_agent_brain.contracts.scene import SceneConfig, TransformProperties
from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent
from robot_agent_brain.contracts.turn import SceneQueryIntent, SceneEditIntent, SceneEditPlan, BrainTurn
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.spatial_facts import SpatialFactResolver
from robot_agent_brain.scene.scene_layout import SceneLayoutPolicy
from robot_agent_brain.scene.scene_graph import world_transform, WorldTransform
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from test_component_runtime import object_
from component_fixtures import named_objects


def entity(name="apple", **kw):
    return TaskEntity(entity_id=name, semantic_name=name, category="surface" if name == "table" else "fruit", **kw)


def supported_scene():
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="continuity", objects=[
        object_(0, "table", "surface", position=(0, 0, -.025), metadata_ref="$DEMO_LIBRARY/1"),
        object_(1, "apple", position=(-.25, 0, .045), metadata_ref="$DEMO_LIBRARY/2", support=0),
        object_(2, "banana", position=(.25, 0, .025), metadata_ref="$DEMO_LIBRARY/3", support=0)])


def transform(position=(0, 0, 0), scale=(1, 1, 1), quaternion_xyzw=(0, 0, 0, 1)):
    return TransformProperties(position=position, scale=scale, quaternion_xyzw=quaternion_xyzw, parent=None)


def set_transform(scene, identifier, **values):
    component = SceneIndex(scene).component(identifier, "Transform")
    component.properties = transform(**values).model_dump(mode="json")


def on_query():
    return SceneQueryIntent(query_type="count", entities=[entity(), entity("table")], target="apple",
        relations=[dict(scope="selection", subject="apple", relation="on", reference="table")])


def edit_plan(operation, target="apple", reference=None, **values):
    return SceneEditPlan(entities=[entity(target)] + ([entity(reference)] if reference else []),
        operations=[SceneEditIntent(operation=operation, target=target, reference=reference, **values)])


@pytest.mark.parametrize("legacy", [dict(semantic_name="apple", category="fruit"), dict(referent_scene_object_id="apple_01")])
def test_q_c01_c02_legacy_fields_are_removed_not_adapted(legacy):
    with pytest.raises(ValidationError):
        SceneQueryIntent(query_type="count", **legacy)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SceneQueryIntent(query_type="count", entities=[entity()], target="apple", **legacy)


@pytest.mark.parametrize("updates", [dict(target="missing"), dict(entities=[]),
    dict(relations=[dict(scope="goal", subject="apple", relation="right")]),
    dict(relations=[dict(scope="selection", subject="apple", relation="on", reference="missing")])])
def test_query_validates_target_entities_and_selection_scope(updates):
    with pytest.raises(ValidationError):
        SceneQueryIntent.model_validate(dict(query_type="count", entities=[entity()], target="apple") | updates)


@pytest.mark.parametrize("name,category,color", [("apple","fruit",None), ("苹果","fruit",None),
    ("apple","水果",None), ("apple","fruit","red"), ("apple","fruit","blue")])
def test_q_c03_q_a01_a03_queries_share_alias_category_color_rules(name, category, color):
    scene = supported_scene()
    scene.objects.append(object_(3, "apple", position=(-.25, .2, .045), metadata_ref="$DEMO_LIBRARY/2", support=0))
    query = SceneQueryIntent(query_type="count", entities=[TaskEntity(entity_id="a", semantic_name=name, category=category, color=color)], target="a")
    kwargs = dict(category_aliases={"水果":"fruit"}, aliases={"苹果":"apple"})
    task = TaskIntent(instruction="selection", entities=[query.entities[0].model_copy(update={"quantity_mode":"all", "all_available":True})], operations=[])
    if color is not None:
        for action in (lambda: SceneQueryEngine(**kwargs).query(query, scene),
                       lambda: SceneGrounder(**kwargs).ground(task, scene)):
            with pytest.raises(ValueError, match="grounding_evidence_missing: color"):
                action()
    else:
        assert SceneQueryEngine(**kwargs).query(query, scene).count == 2
        assert len(SceneGrounder(**kwargs).ground(task, scene).entities[0].scene_object_ids) == 2


def test_query_candidate_pool_validates_before_relation_filter():
    query = SceneQueryIntent(query_type="position", entities=[entity(quantity_mode="candidate_pool", count=2)],
        relations=[dict(scope="selection", subject="apple", relation="rightmost")], target="apple")
    with pytest.raises(ValueError, match="candidate_pool_count_mismatch"):
        SceneQueryEngine().query(query, supported_scene())


def test_d_c01_c02_plural_query_focus_then_edit_preserves_entire_set():
    scene = supported_scene()
    scene.objects.append(object_(3, "apple", position=(-.25,.2,.045), metadata_ref="$DEMO_LIBRARY/2", support=0))
    session = BrainSession(scene, BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())
    session.dialogue = DialogueState(last_entity_ids=[1, 3])
    assert session.dialogue.contextualize("它们有几个？", scene) == "它们有几个？ [dialogue_ref_set=apple]"
    selector = entity(dialogue_ref_set=True, quantity_mode="all", all_available=True)
    result = session.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="它们有几个？",
        scene_query=SceneQueryIntent(query_type="count", entities=[selector], target="apple")))
    assert result.scene_query_result.count == 2
    assert session.dialogue.last_entity_ids == [1, 3]
    with pytest.raises(ValueError, match="dialogue_reference_ambiguous"):
        session.dialogue.contextualize("它在哪里？", session.scene)
    session.process_turn("move", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="把它们向右移动五厘米",
        scene_edit=SceneEditPlan(entities=[selector], operations=[SceneEditIntent(operation="translate", target="apple", direction="right", distance_m=.05)])))
    apples = named_objects(session.scene, "apple")
    assert [o.object_id_in_scene for o in apples] == session.dialogue.last_entity_ids == [1, 3]
    assert [world_transform(session.scene, o.object_id_in_scene).position[0] for o in apples] == pytest.approx([-.2, -.2])


@pytest.mark.parametrize("target,reference,scale", [("apple","banana",1), ("banana","apple",1), ("apple","banana",2)])
def test_l_z01_z03_planar_relative_moves_preserve_support_height(target, reference, scale):
    scene, assets = supported_scene(), BrainConfig().load_assets()
    obj = named_objects(scene, target)[0]
    x, y, z = world_transform(scene, obj.object_id_in_scene).position
    set_transform(scene, obj.object_id_in_scene, position=(x, y, z*scale), scale=(1, 1, scale))
    patch = SceneEditor(assets).edit(edit_plan("move_relative", target, reference, relation="right_of"), scene)
    final = SceneManager(scene).apply_patch(patch)
    world = world_transform(final, obj.object_id_in_scene)
    assert world.position[2] == z*scale
    assert world_bounds(assets.resolve(SceneIndex(final).metadata_ref(obj.object_id_in_scene)), world)[0][2] == pytest.approx(0)
    assert SceneIndex(final).semantic(obj.object_id_in_scene).support == 0
    assert final.scene_version == 1


def test_l_z04_relative_add_uses_verified_support_and_own_bottom():
    scene, assets = supported_scene(), BrainConfig().load_assets()
    scene.objects.pop()
    final = SceneManager(scene).apply_patch(SceneEditor(assets).edit(edit_plan("add", "banana", "apple", relation="right_of"), scene))
    banana = named_objects(final, "banana")[0].object_id_in_scene
    assert world_transform(final, banana).position[0] > world_transform(scene, 1).position[0]
    assert world_transform(final, banana).position[2] == pytest.approx(.025)
    assert SceneIndex(final).semantic(banana).support == 0


@pytest.mark.parametrize("direction,distance,expected", [("right",.05,1), ("up",.1,0), ("left",.7,0)])
def test_f_s01_s04_support_continuity_and_no_guessed_membership(direction, distance, expected):
    scene, assets = supported_scene(), BrainConfig().load_assets()
    patch = SceneEditor(assets).edit(edit_plan("translate", direction=direction, distance_m=distance), scene)
    assert [op.action for op in patch.operations] == ["upsert_component", "upsert_component"]
    final = SceneManager(scene).apply_patch(patch)
    semantic = SceneIndex(final).semantic(1)
    assert semantic.support == (0 if expected else None)
    assert set(semantic.model_dump()) == {"semantic_name", "category", "support"}
    if expected:
        query = on_query()
        ground = SceneGrounder().ground(TaskIntent(instruction="on", entities=query.entities, operations=[], spatial_relations=query.relations), final)
        assert ground.entities[0].scene_object_id == 1
    assert SceneQueryEngine().query(on_query(), final).count == expected


def test_relative_add_without_verified_or_default_support_is_rejected():
    scene = supported_scene()
    set_transform(scene, 1, position=(-.25, 0, .2))
    with pytest.raises(ValueError, match="scene_edit_support_unknown"):
        SceneEditor(BrainConfig().load_assets()).edit(edit_plan("add", "banana", "apple", relation="right_of"), scene)


def test_world_bounds_respect_offset_aabb_scale_and_quaternion():
    model = AssetGeometry(dimensions_m=(1,2,3), local_aabb_min_m=(0,0,0), local_aabb_max_m=(1,2,3))
    low, high = world_bounds(model, transform(position=(1,2,3), scale=(2,3,4), quaternion_xyzw=(0,0,math.sqrt(.5),math.sqrt(.5))))
    assert low == pytest.approx((-5,2,3))
    assert high == pytest.approx((1,4,15))
    with pytest.raises(ValidationError):
        AssetGeometry.model_validate({"dimensions_m": [1, 2, 3]})


def test_yawed_support_uses_oriented_footprint_and_tilt_is_not_inferred():
    assets, scene = BrainConfig().load_assets(), supported_scene()
    apple = scene.objects[1]
    set_transform(scene, 0, position=(0,0,-.025), quaternion_xyzw=(0,0,math.sin(math.pi/8),math.cos(math.pi/8)))
    set_transform(scene, 1, position=(.75,.75,.045))
    assert SpatialFactResolver(assets).infer_support(apple, scene) is None
    set_transform(scene, 1, position=(0,0,.045))
    assert SpatialFactResolver(assets).infer_support(apple, scene) == 0
    set_transform(scene, 0, quaternion_xyzw=(math.sin(.1),0,0,math.cos(.1)))
    assert SpatialFactResolver(assets).infer_support(apple, scene) is None


def test_free_space_is_not_an_above_alias():
    model = BrainConfig().load_assets().resolve("$DEMO_LIBRARY/2")
    with pytest.raises(ValueError, match="unsupported_scene_layout_relation"):
        SceneLayoutPolicy().relative_transform("free_space", transform(), model, model)


def test_planar_layout_requires_caller_provided_height():
    model = BrainConfig().load_assets().resolve("$DEMO_LIBRARY/2")
    with pytest.raises(ValueError, match="support_transform_required"):
        SceneLayoutPolicy().relative_transform("right_of", transform(), model, model)


def test_support_tolerance_is_configurable_not_a_position_compensation():
    scene = supported_scene()
    set_transform(scene, 1, position=(-.25,0,.0465))
    assets = BrainConfig().load_assets()
    assert SpatialFactResolver(assets, support_contact_tolerance_m=.001).infer_support(scene.objects[1], scene) is None
    assert SpatialFactResolver(assets, support_contact_tolerance_m=.002).infer_support(scene.objects[1], scene) == 0
    assert world_transform(scene, 1).position[2] == .0465


def test_support_transform_uses_offset_origin_and_scaled_geometry():
    scene, assets = supported_scene(), BrainConfig().load_assets()
    model = AssetGeometry(dimensions_m=(.1,.1,.1), local_aabb_min_m=(-.05,-.05,-.02), local_aabb_max_m=(.05,.05,.08))
    placed = SpatialFactResolver(assets).support_transform(model, scene.objects[0], scene, x=.1, y=.2,
        existing=WorldTransform.from_local(transform(scale=(1,1,2), quaternion_xyzw=(0,0,math.sqrt(.5),math.sqrt(.5)))))
    assert placed.position == pytest.approx((.1,.2,.04))
    assert world_bounds(model, placed)[0][2] == pytest.approx(0)


def test_default_support_fallback_is_explicit_and_geometry_checked():
    scene = supported_scene()
    scene.objects.pop()
    set_transform(scene, 1, position=(-.25,0,.2))
    config = BrainConfig()
    patch = SceneEditor(config.load_assets()).edit(edit_plan("add", "banana", "apple", relation="right_of"), scene,
                                                  defaults=config.load_defaults())
    final = SceneManager(scene).apply_patch(patch)
    identifier = final.objects[-1].object_id_in_scene
    assert world_transform(final, identifier).position[2] == pytest.approx(.025)
    assert SceneIndex(final).semantic(identifier).support == 0

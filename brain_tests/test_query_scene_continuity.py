import math
import pytest
from pydantic import ValidationError
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform, ModelProperty
from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent
from robot_agent_brain.contracts.turn import SceneQueryIntent, SceneEditIntent, SceneEditPlan, BrainTurn
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.spatial_facts import SpatialFactResolver
from robot_agent_brain.scene.scene_layout import SceneLayoutPolicy
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform


def entity(name="apple", **kw):
    return TaskEntity(entity_id=name, semantic_name=name, category="surface" if name == "table" else "fruit", **kw)


def supported_scene():
    return SceneConfig(scene_id="continuity", objects=[
        SceneObject(scene_object_id="table_01", asset_id="demo_table", semantic_name="table", category="surface",
                    transform=Transform(position=(0, 0, -.025))),
        SceneObject(scene_object_id="apple_01", asset_id="demo_apple", semantic_name="apple", category="fruit",
                    transform=Transform(position=(-.25, 0, .045)),
                    properties={"support":"table_01", "support_relation":"on", "aliases":["苹果"], "color":"red"}),
        SceneObject(scene_object_id="banana_01", asset_id="demo_banana", semantic_name="banana", category="fruit",
                    transform=Transform(position=(.25, 0, .025)), properties={"support":"table_01"})])


def on_query():
    return SceneQueryIntent(query_type="count", entities=[entity(), entity("table")], target="apple",
        relations=[dict(scope="selection", subject="apple", relation="on", reference="table")])


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


@pytest.mark.parametrize("name,category,color,count", [("apple","fruit",None,2), ("苹果","fruit",None,2),
    ("apple","水果",None,2), ("apple","fruit","red",1), ("apple","fruit","blue",0)])
def test_q_c03_q_a01_a03_queries_share_alias_category_color_rules(name, category, color, count):
    scene = supported_scene()
    scene.objects.append(scene.objects[1].model_copy(update={"scene_object_id":"apple_02", "properties":{"aliases":["苹果"], "color":"green"}}))
    query = SceneQueryIntent(query_type="count", entities=[TaskEntity(entity_id="a", semantic_name=name, category=category, color=color)], target="a")
    assert SceneQueryEngine(category_aliases={"水果":"fruit"}).query(query, scene).count == count
    if count:
        task = TaskIntent(instruction="selection", entities=[query.entities[0].model_copy(update={"quantity_mode":"all", "all_available":True})], operations=[])
        ground = SceneGrounder(category_aliases={"水果":"fruit"}).ground(task, scene)
        assert len(ground.entities[0].scene_object_ids) == count


def test_query_candidate_pool_validates_before_relation_filter():
    query = SceneQueryIntent(query_type="position", entities=[entity(quantity_mode="candidate_pool", count=2)],
        relations=[dict(scope="selection", subject="apple", relation="rightmost")], target="apple")
    with pytest.raises(ValueError, match="candidate_pool_count_mismatch"):
        SceneQueryEngine().query(query, supported_scene())


def test_d_c01_c02_plural_query_focus_then_edit_preserves_entire_set():
    scene = supported_scene()
    scene.objects.append(scene.objects[1].model_copy(update={"scene_object_id":"apple_02", "transform":Transform(position=(-.25,.2,.045))}))
    session = BrainSession(scene, BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())
    session.dialogue = DialogueState(last_entity_ids=["apple_01", "apple_02"])
    contextualized = session.dialogue.contextualize("它们有几个？", scene)
    assert contextualized == "它们有几个？ [dialogue_ref_set=apple]"
    assert "apple_01" not in contextualized and "apple_02" not in contextualized
    selector = entity(dialogue_ref_set=True, quantity_mode="all", all_available=True)
    result = session.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="它们有几个？",
        scene_query=SceneQueryIntent(query_type="count", entities=[selector], target="apple")))
    assert result.scene_query_result.count == 2
    assert session.dialogue.last_entity_ids == ["apple_01", "apple_02"]
    with pytest.raises(ValueError, match="dialogue_reference_ambiguous"):
        session.dialogue.contextualize("它在哪里？", session.scene)
    session.process_turn("move", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="把它们向右移动五厘米",
        scene_edit=SceneEditPlan(entities=[selector], operations=[SceneEditIntent(operation="translate", target="apple", direction="right", distance_m=.05)])))
    apples = [o for o in session.scene.objects if o.semantic_name == "apple"]
    assert [o.scene_object_id for o in apples] == session.dialogue.last_entity_ids == ["apple_01", "apple_02"]
    assert [o.transform.position[0] for o in apples] == pytest.approx([-.2, -.2])


@pytest.mark.parametrize("target,reference,scale", [("apple","banana",1), ("banana","apple",1), ("apple","banana",2)])
def test_l_z01_z03_planar_relative_moves_preserve_support_height(target, reference, scale):
    scene = supported_scene()
    assets = BrainConfig().load_assets()
    obj = next(o for o in scene.objects if o.semantic_name == target)
    x,y,z = obj.transform.position
    obj.transform = Transform(position=(x,y,z*scale), scale=(1,1,scale))
    patch = SceneEditor(assets).edit(SceneEditIntent(operation="move_relative", semantic_name=target,
        category="fruit", reference=reference, relation="right_of"), scene)
    final = SceneManager(scene).apply_patch(patch)
    moved = next(o for o in final.objects if o.semantic_name == target)
    assert moved.transform.position[2] == z*scale
    assert SpatialFactResolver(assets).bounds(assets.get_model_property(moved.asset_id), moved.transform)[0][2] == pytest.approx(0)
    assert moved.properties["support"] == "table_01" and moved.properties["support_relation"] == "on"
    assert final.scene_version == 1


def test_l_z04_relative_add_uses_verified_support_and_own_bottom():
    scene = supported_scene()
    scene.objects.pop()  # remove existing banana
    assets = BrainConfig().load_assets()
    patch = SceneEditor(assets).edit(SceneEditIntent(operation="add", semantic_name="banana", category="fruit",
        reference="apple", relation="right_of"), scene)
    final = SceneManager(scene).apply_patch(patch)
    banana = next(o for o in final.objects if o.semantic_name == "banana")
    assert banana.transform.position[0] > scene.objects[1].transform.position[0]
    assert banana.transform.position[2] == pytest.approx(.025)
    assert banana.properties["support"] == "table_01"


@pytest.mark.parametrize("direction,distance,expected", [("right",.05,1), ("up",.1,0), ("left",.7,0)])
def test_f_s01_s04_support_continuity_and_no_guessed_membership(direction, distance, expected):
    scene = supported_scene()
    scene.objects[1].properties["container_membership"] = "box_01"
    assets = BrainConfig().load_assets()
    patch = SceneEditor(assets).edit(SceneEditIntent(operation="translate", semantic_name="apple", category="fruit",
        direction=direction, distance_m=distance), scene)
    assert [op.action for op in patch.operations] == ["update_transform", "update_property"]
    final = SceneManager(scene).apply_patch(patch)
    apple = final.objects[1]
    assert "container_membership" not in apple.properties
    if expected:
        assert apple.properties["support"] == "table_01" and apple.properties["support_relation"] == "on"
        query = on_query()
        ground = SceneGrounder().ground(TaskIntent(instruction="on", entities=query.entities, operations=[], spatial_relations=query.relations), final)
        assert ground.entities[0].scene_object_id == "apple_01"
    else:
        assert "support" not in apple.properties and "support_relation" not in apple.properties
    assert SceneQueryEngine().query(on_query(), final).count == expected


def test_relative_add_without_verified_or_default_support_is_rejected():
    scene = supported_scene()
    scene.objects[1].transform = Transform(position=(-.25,0,.2))
    with pytest.raises(ValueError, match="scene_edit_support_unknown"):
        SceneEditor(BrainConfig().load_assets()).edit(SceneEditIntent(operation="add", semantic_name="banana",
            category="fruit", relation="right_of", reference="apple"), scene)


def test_world_bounds_respect_offset_aabb_scale_and_quaternion():
    model = ModelProperty(asset_id="offset", semantic_name="offset", category="fruit", dimensions_m=(1,2,3), aabb_m=(0,0,0,1,2,3))
    low, high = world_bounds(model, Transform(position=(1,2,3), scale=(2,3,4), quaternion_xyzw=(0,0,math.sqrt(.5),math.sqrt(.5))))
    assert low == pytest.approx((-5,2,3))
    assert high == pytest.approx((1,4,15))
    with pytest.raises(ValueError, match="origin_unknown"):
        world_bounds(model.model_copy(update={"aabb_m":None}), Transform())


def test_yawed_support_uses_oriented_footprint_and_tilt_is_not_inferred():
    assets = BrainConfig().load_assets()
    scene = supported_scene()
    table, apple = scene.objects[:2]
    table.transform = Transform(position=(0,0,-.025), quaternion_xyzw=(0,0,math.sin(math.pi/8), math.cos(math.pi/8)))
    apple.transform = Transform(position=(.75,.75,.045))
    assert SpatialFactResolver(assets).infer_support(apple, scene) is None
    apple.transform = Transform(position=(0,0,.045))
    assert SpatialFactResolver(assets).infer_support(apple, scene) == "table_01"
    table.transform = Transform(quaternion_xyzw=(math.sin(.1),0,0,math.cos(.1)))
    assert SpatialFactResolver(assets).infer_support(apple, scene) is None


def test_free_space_is_not_an_above_alias():
    model = BrainConfig().load_assets().get_model_property("demo_apple")
    with pytest.raises(ValueError, match="unsupported_scene_layout_relation"):
        SceneLayoutPolicy().relative_transform("free_space", Transform(), model, model)


def test_planar_layout_requires_caller_provided_height():
    model = BrainConfig().load_assets().get_model_property("demo_apple")
    with pytest.raises(ValueError, match="support_transform_required"):
        SceneLayoutPolicy().relative_transform("right_of", Transform(), model, model)


def test_support_tolerance_is_configurable_not_a_position_compensation():
    scene = supported_scene()
    scene.objects[1].transform.position = (-.25,0,.0465)
    assets = BrainConfig().load_assets()
    assert SpatialFactResolver(assets, support_contact_tolerance_m=.001).infer_support(scene.objects[1], scene) is None
    assert SpatialFactResolver(assets, support_contact_tolerance_m=.002).infer_support(scene.objects[1], scene) == "table_01"
    assert scene.objects[1].transform.position[2] == .0465


def test_support_transform_uses_offset_origin_and_scaled_geometry():
    scene = supported_scene()
    assets = BrainConfig().load_assets()
    model = ModelProperty(asset_id="offset", semantic_name="offset", category="fruit", dimensions_m=(.1,.1,.1), aabb_m=(-.05,-.05,-.02,.05,.05,.08))
    transform = SpatialFactResolver(assets).support_transform(model, scene.objects[0], x=.1, y=.2,
        existing=Transform(scale=(1,1,2), quaternion_xyzw=(0,0,math.sqrt(.5),math.sqrt(.5))))
    assert transform.position == pytest.approx((.1,.2,.04))
    assert world_bounds(model, transform)[0][2] == pytest.approx(0)


def test_default_support_fallback_is_explicit_and_geometry_checked():
    scene = supported_scene()
    scene.objects.pop()
    scene.objects[1].transform.position = (-.25,0,.2)
    config = BrainConfig()
    patch = SceneEditor(config.load_assets()).edit(SceneEditIntent(operation="add", semantic_name="banana",
        category="fruit", relation="right_of", reference="apple"), scene, defaults=config.load_defaults())
    final = SceneManager(scene).apply_patch(patch)
    assert final.objects[-1].transform.position[2] == pytest.approx(.025)
    assert final.objects[-1].properties["support"] == "table_01"

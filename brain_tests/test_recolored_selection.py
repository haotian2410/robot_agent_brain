"""Selection after a scene object is painted away from its catalogued colour.

Shapes these tests after session 5c6146f9: three apples, one of which an
earlier turn recolored green, and a catalogued 青苹果 that no user ever painted.
"""
import pytest

from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.scene import SceneComponent, SceneConfig
from robot_agent_brain.contracts.spatial import SpatialRelation
from robot_agent_brain.contracts.task_intent import QuantityMode, TaskEntity, TaskIntent
from robot_agent_brain.contracts.turn import SceneQueryIntent
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.grounding.semantic_entity_selector import SemanticEntitySelector
from robot_agent_brain.scene.query import SceneQueryEngine
from test_component_runtime import object_

GREEN, UNPALETTE = "#00FF00", "#123456"


class Library:
    """The live OLS shape: tags say what an object is, and no asset declares a colour."""

    typed_namespaces = True
    models = {"apple": ("apple", ("苹果", "水果")),
              "green_apple": ("green_apple", ("青苹果", "水果")),
              "cup": ("cup", ("杯子", "花纹")),
              "mug": ("mug", ("杯子", "浮雕纹"))}

    def resolve(self, ref, kind=None):
        name, tags = self.models[ref]
        return BrainAssetView(library_asset_id=1, metadata_ref=ref, semantic_name=name, tags=tags,
                              dimensions_m=(.1, .1, .1), local_aabb_min_m=(-.05, -.05, 0),
                              local_aabb_max_m=(.05, .05, .1))


def item(oid, x, name="apple", ref="apple", category="fruit", colour=None):
    obj = object_(oid, name, category=category, position=(x, 0, 0), metadata_ref=ref)
    if colour is not None:
        obj.components.append(SceneComponent(component_type="MeshRenderer",
                                             properties={"forceOverrideColor": colour}))
    return obj


def scene_(*items):
    return SceneConfig(scene_schema_version=1, scene_id=1, scene_version=1, scene_name="painted",
                      objects=[object_(0, "table", "surface"), *items])


def three_apples():
    # 34 was repainted green by an earlier turn; 35 and 36 never were.
    return scene_(item(34, -.1, colour=GREEN), item(35, 0.), item(36, .1))


def entity_(name="apple", **kwargs):
    return TaskEntity(entity_id=name, semantic_name=name, category="fruit", **kwargs)


def select(scene, entity, relations=(), *, fallback=False):
    return [obj.object_id_in_scene for obj in SemanticEntitySelector(assets=Library()).select(
        entity.entity_id, [entity], list(relations), scene, allow_description_fallback=fallback)]


def test_a_painted_apple_is_found_by_its_new_colour():
    assert select(three_apples(), entity_(color="green")) == [34]


def test_a_literal_hex_paint_is_matched_exactly():
    assert select(three_apples(), entity_(color=GREEN)) == [34]


def test_colour_may_arrive_as_a_tag_and_stays_a_hard_filter():
    scene = scene_(item(33, -.2, name="green_apple", ref="green_apple"),
                   item(34, -.1, colour=GREEN), item(35, 0.), item(36, .1))
    described = TaskEntity(entity_id="apple", semantic_name="uncatalogued", category="fruit",
                           tags=["绿色", "苹果"])
    # 「绿色的苹果」 is the painted apple, never the catalogued 青苹果: the colour
    # word filters, and 青苹果 shares no token with 「绿色苹果」.
    assert select(scene, described) == [34]
    assert select(scene, entity_("green_apple")) == [33]


def test_a_colour_nothing_declares_is_dropped_rather_than_refused():
    # No apple here ever declared a colour, so 「红色的」 cannot be checked and must
    # not end the turn: the subject survives and the ambiguity rule asks which one.
    scene = scene_(item(35, 0.), item(36, .1))
    assert select(scene, entity_(color="red"), fallback=True) == [35, 36]
    assert select(scene, entity_(color="red")) == [35, 36]


def test_a_bulk_quantity_on_a_colourless_pool_selects_the_subjects():
    scene = scene_(item(35, 0.), item(36, .1))
    bulk = entity_(color="red", quantity_mode=QuantityMode.ALL, count=2, all_available=True)
    assert select(scene, bulk, fallback=True) == [35, 36]


def test_a_colour_the_paint_system_cannot_express_is_no_filter_at_all():
    scene = scene_(item(34, -.1, colour=GREEN), item(35, 0.))
    assert select(scene, entity_(color="彩色")) == [34, 35]


def test_red_does_not_relax_into_every_apple():
    assert select(three_apples(), entity_(color="red"), fallback=True) == []


def test_an_extremum_selects_from_the_relaxed_pool():
    relation = SpatialRelation(subject="apple", relation="rightmost")
    assert select(three_apples(), entity_(color="red"), [relation], fallback=True) == [36]


def test_a_single_apple_needs_no_colour_evidence_to_be_the_one():
    assert select(scene_(item(34, 0., colour=GREEN)), entity_(color="red"), fallback=True) == [34]


def test_a_paint_outside_the_named_palette_keeps_its_hex_evidence():
    scene = scene_(item(34, -.1, colour=UNPALETTE), item(35, 0.), item(36, .1))
    assert select(scene, entity_(color=UNPALETTE)) == [34]
    assert select(scene, entity_(color="green")) == []


def test_a_bulk_quantity_never_relaxes():
    bulk = entity_(color="red", quantity_mode=QuantityMode.ALL, count=3, all_available=True)
    assert select(three_apples(), bulk, fallback=True) == []


def test_the_grounder_reports_a_miss_instead_of_an_arbitrary_apple():
    intent = TaskIntent(instruction="把红色的苹果拿起来", entities=[entity_(color="red")], operations=[])
    with pytest.raises(ValueError, match="grounding_missing: apple"):
        SceneGrounder(assets=Library()).ground(intent, three_apples())


def test_the_grounder_accepts_the_extremum_relaxation():
    entity = entity_(color="red")
    intent = TaskIntent(instruction="把最右边的红苹果拿起来", entities=[entity], operations=[],
                        spatial_relations=[SpatialRelation(subject="apple", relation="rightmost")])
    task = SceneGrounder(assets=Library()).ground(intent, three_apples())
    assert task.entities[0].scene_object_id == 36


def test_a_count_never_relaxes():
    engine = SceneQueryEngine(assets=Library())

    def count(colour):
        return engine.query(SceneQueryIntent(query_type="count", target="apple",
                                             entities=[entity_(color=colour)]), three_apples()).count

    assert count("red") == 0
    assert count("green") == 1


def test_tags_reach_instances_the_parsed_name_missed():
    # Qwen may slug 「绿色的苹果」 as green_apple while every instance is apple.
    assert select(three_apples(), TaskEntity(entity_id="apple", semantic_name="green_apple",
                                             category="fruit", tags=["苹果"])) == [34, 35, 36]


def test_a_tag_shared_by_several_assets_stays_ambiguous():
    scene = scene_(item(35, 0., name="cup", ref="cup", category="tableware"),
                   item(36, .1, name="mug", ref="mug", category="tableware"))
    entity = TaskEntity(entity_id="cup", semantic_name="tumbler", category="tableware", tags=["杯子"])
    assert select(scene, entity) == [35, 36]
    with pytest.raises(ValueError, match="grounding_ambiguous"):
        SceneGrounder(assets=Library()).ground(
            TaskIntent(instruction="把杯子拿起来", entities=[entity], operations=[]), scene)

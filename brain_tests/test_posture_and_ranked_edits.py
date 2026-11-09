from types import SimpleNamespace

import pytest

from robot_agent_brain.contracts.turn import SceneEditPlan
from robot_agent_brain.models.qwen_http import _repair_live_scene_edit_quantity, _repair_live_posture_clarification
from robot_agent_brain.models.task_understanding import parse_qwen_turn, task_understanding_v3_wire_schema
from robot_agent_brain.scene.editor import SceneEditor
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.posture import posture_transform, fit_support
from robot_agent_brain.scene.scene_graph import WorldTransform, world_transform
from robot_agent_brain.scene.scene_manager import SceneManager
from robot_agent_brain.scene.component_access import SceneIndex
from test_scene_scale_color import fixture
from test_scene_edit_selection_counts import scene_with_apples, apples
from robot_agent_brain.config import BrainConfig


def test_ranked_two_selects_frontmost_members_not_lowest_ids():
    scene = scene_with_apples()
    plan = SceneEditPlan(entities=[apples(count=2, mode="all", subset=True)],
        relations=[dict(subject="target", relation="frontmost")],
        operations=[dict(operation="remove", target="target")])
    result = SceneEditor(BrainConfig().load_assets()).edit_result(plan, scene)
    assert result.deleted_object_ids == [3, 5]


def test_ranked_instruction_removes_invented_ids_and_retains_relation():
    catalog = SimpleNamespace(models=[SimpleNamespace(name="rubiks_cube", aliases=["魔方"])])
    payload = dict(status="accepted", turn_kind="scene_edit", scene_edit=dict(
        entities=[dict(entity_id="cube", semantic_name="rubiks_cube", category="toy", count=2,
                       quantity_mode="all", scene_object_ids=[18, 19])], relations=[],
        operations=[dict(operation="remove", target="cube")]))
    result = _repair_live_scene_edit_quantity(payload, "把最前面的两个魔方删除", catalog)
    assert result["scene_edit"]["entities"][0]["scene_object_ids"] == []
    assert result["scene_edit"]["relations"][0]["relation"] == "frontmost"


@pytest.mark.parametrize("posture,height", [("flat", .1), ("upright", .5)])
def test_posture_uses_scaled_axes_and_remains_supported(posture, height):
    library, scene = fixture()
    model = library.models["basket"].model_copy(update={
        "dimensions_m": (.1, .3, .5), "local_aabb_min_m": (-.05, -.15, -.25),
        "local_aabb_max_m": (.05, .15, .25)})
    library.models["basket"] = model
    SceneIndex(scene).component(1, "Transform").properties["position"] = [0, 0, .25]
    plan = SceneEditPlan(entities=[dict(entity_id="b", semantic_name="basket", category="container")],
                         operations=[dict(operation="orient", posture=posture, target="b")])
    result = SceneEditor(library).edit_result(plan, scene)
    updated = SceneManager(scene).apply_patch(result.patch)
    bounds = world_bounds(model, world_transform(updated, 1))
    assert bounds[0][2] == pytest.approx(0)
    assert bounds[1][2] == pytest.approx(height)
    assert SceneIndex(updated).semantic(1).support == 0
    assert SceneIndex(scene).transform(1).position == (0, 0, .25)


def test_equal_axes_and_nonuniform_scale_choose_deterministic_pose():
    model = SimpleNamespace(local_aabb_min_m=(-.5, -.5, -.5), local_aabb_max_m=(.5, .5, .5))
    world = WorldTransform((0, 0, 0), ((1., 0, 0), (0, 2., 0), (0, 0, 3.)))
    flat = posture_transform(model, world, "flat")
    upright = posture_transform(model, world, "upright")
    assert world_bounds(model, flat)[1][2] == .5
    assert world_bounds(model, upright)[1][2] == 1.5
    equal = WorldTransform((0, 0, 0), ((1., 0, 0), (0, 1., 0), (0, 0, 1.)))
    assert posture_transform(model, equal, "flat") == posture_transform(model, equal, "upright")


def test_simple_posture_request_recovers_provider_clarification():
    catalog = SimpleNamespace(models=[SimpleNamespace(name="sugar_box", aliases=["糖盒"],
                                                       asset_key="model:19", category="object")])
    value = dict(status="clarification_required", turn_kind="robot_task", clarification_question="Which axis?")
    result = _repair_live_posture_clarification(value, "把糖盒放平", catalog)
    turn = parse_qwen_turn(result, "把糖盒放平")
    assert turn.scene_edit.operations[0].posture == "flat"


@pytest.mark.parametrize("word,posture", [("放倒", "flat"), ("立起来", "upright")])
@pytest.mark.parametrize("supplied", [False, True])
def test_accepted_orient_missing_posture_is_completed_from_explicit_instruction(word, posture, supplied):
    catalog = SimpleNamespace(models=[SimpleNamespace(name="bottle", aliases=["瓶子"],
                                                       asset_key="model:14", category="appliance")])
    operation = dict(operation="orient", target="bottle")
    if supplied:
        operation["posture"] = None
    entity = dict(entity_id="bottle", semantic_name="bottle", category="appliance")
    value = dict(status="accepted", turn_kind="scene_edit", scene_edit=dict(
        entities=[entity], relations=[], operations=[operation]))
    instruction = f"把瓶子{word}"
    repaired = _repair_live_posture_clarification(value, instruction, catalog)
    turn = parse_qwen_turn(repaired, instruction)
    assert turn.scene_edit.operations[0].posture == posture
    assert "posture" not in operation or operation["posture"] is None
    assert repaired["scene_edit"]["entities"] == [entity]


def test_posture_field_is_required_in_provider_schema_even_when_null():
    schema = task_understanding_v3_wire_schema()
    assert "posture" in schema["$defs"]["SceneEditIntent"]["required"]


def test_missing_posture_repair_does_not_replace_existing_pose_or_target():
    catalog = SimpleNamespace(models=[SimpleNamespace(name="bottle", aliases=["瓶子"],
                                                       asset_key="model:14", category="appliance")])
    for operation, name in [(dict(operation="orient", target="b", posture="upright"), "bottle"),
                            (dict(operation="rotate", target="b", axis="x", angle_deg=90), "bottle"),
                            (dict(operation="orient", target="b"), "sugar_box")]:
        value = dict(status="accepted", turn_kind="scene_edit", scene_edit=dict(
            entities=[dict(entity_id="b", semantic_name=name, category="object")],
            operations=[operation]))
        assert _repair_live_posture_clarification(value, "把瓶子放倒", catalog) is value


def test_support_fitting_moves_only_the_amount_required_at_an_edge():
    model = SimpleNamespace(local_aabb_min_m=(-.1, -.1, -.1), local_aabb_max_m=(.1, .1, .1))
    support = SimpleNamespace(local_aabb_min_m=(-1., -1., -.2), local_aabb_max_m=(1., 1., 0.))
    identity = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    pose = fit_support(model, WorldTransform((.95, .25, .5), identity),
                       support, WorldTransform((0, 0, 0), identity))
    assert pose.position == pytest.approx((.9, .25, .1))
    oversized = SimpleNamespace(local_aabb_min_m=(-2., -.1, -.1), local_aabb_max_m=(2., .1, .1))
    with pytest.raises(ValueError, match="footprint_exceeded"):
        fit_support(oversized, WorldTransform((0, 0, 0), identity),
                    support, WorldTransform((0, 0, 0), identity))


def test_posture_collision_fails_without_mutating_scene():
    library, scene = fixture()
    library.models["basket"] = library.models["basket"].model_copy(update={
        "dimensions_m": (.1, .2, .8), "local_aabb_min_m": (-.05, -.1, -.4),
        "local_aabb_max_m": (.05, .1, .4)})
    SceneIndex(scene).component(1, "Transform").properties["position"] = [0, 0, .4]
    for identifier, x, y in ((2, .25, 0), (3, -.25, 0), (4, 0, .25), (5, 0, -.25)):
        other = scene.objects[1].model_copy(deep=True)
        other.object_id_in_scene = identifier
        next(c for c in other.components if c.component_type == "Transform").properties["position"] = [x, y, .4]
        scene.objects.append(other)
    before = scene.model_dump()
    plan = SceneEditPlan(entities=[dict(entity_id="b", semantic_name="basket", category="container",
                                        scene_object_ids=[1])],
                         operations=[dict(operation="orient", posture="flat", target="b")])
    with pytest.raises(ValueError, match="collision"):
        SceneEditor(library).edit_result(plan, scene)
    assert scene.model_dump() == before


def test_posture_tries_another_horizontal_heading_when_first_is_blocked():
    library, scene = fixture()
    library.models["basket"] = library.models["basket"].model_copy(update={
        "dimensions_m": (.1, .2, .8), "local_aabb_min_m": (-.05, -.1, -.4),
        "local_aabb_max_m": (.05, .1, .4)})
    SceneIndex(scene).component(1, "Transform").properties["position"] = [0, 0, .4]
    other = scene.objects[1].model_copy(deep=True)
    other.object_id_in_scene = 2
    next(c for c in other.components if c.component_type == "Transform").properties["position"] = [.25, 0, .4]
    scene.objects.append(other)
    plan = SceneEditPlan(entities=[dict(entity_id="b", semantic_name="basket", category="container",
                                        scene_object_ids=[1])],
                         operations=[dict(operation="orient", posture="flat", target="b")])
    editor = SceneEditor(library)
    result = editor.edit_result(plan, scene)
    updated = SceneManager(scene).apply_patch(result.patch)
    bounds = world_bounds(library.models["basket"], world_transform(updated, 1))
    assert bounds[1][1] - bounds[0][1] == pytest.approx(.8)
    assert bounds[1][2] - bounds[0][2] == pytest.approx(.1)
    assert not editor._overlaps(SceneIndex(updated).object(1), updated)

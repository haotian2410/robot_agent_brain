"""Integration checks for migrated modules, without legacy flat fixtures."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from robot_agent_brain.adapters.scene_file_codec import SceneFileCodec
from robot_agent_brain.contracts.commands import (
    CommandPlacementTarget, ExecutionFeedback, LocateParameters, canonical_commands,
)
from robot_agent_brain.contracts.scene import SceneConfig, SceneComponent, SceneObject, ScenePatch
from robot_agent_brain.contracts.spatial import SpatialRelation, ResolvedSelectionRelation
from robot_agent_brain.contracts.task_intent import TaskEntity, TaskIntent, Operation, PlacementTarget
from robot_agent_brain.contracts.turn import SceneQueryIntent
from robot_agent_brain.errors import BrainError
from robot_agent_brain.grounding.scene_grounder import SceneGrounder
from robot_agent_brain.grounding.semantic_entity_selector import SemanticEntitySelector
from robot_agent_brain.grounding.scene_relation_resolver import SceneRelationResolver
from robot_agent_brain.planning.command_exporter import CommandExporter
from robot_agent_brain.planning.recipe_planner import RecipePlanner
from robot_agent_brain.planning.task_expander import TaskExpander
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.scene.scene_manager import SceneManager


def object_(identifier, name=None, category="fruit", position=(0, 0, 0),
            parent=None, support=None, metadata_ref=None, scale=(1, 1, 1)):
    components = [SceneComponent(component_type="Transform", properties={
        "position": list(position), "quaternion_xyzw": [0, 0, 0, 1],
        "scale": list(scale), "parent": parent})]
    if name is not None:
        components.append(SceneComponent(component_type="Semantic", properties={
            "semantic_name": name, "category": category, "support": support}))
    if metadata_ref:
        components.append(SceneComponent(component_type="MetadataRef", properties={"path": metadata_ref}))
    return SceneObject(object_id_in_scene=identifier, object_name_in_scene="Not a semantic identifier",
                       components=components)


def scene_():
    # ID 0 is the reference. Local -9 is world +1; world -1 is nearer to 0.
    return SceneConfig(scene_schema_version=1, scene_id=0, scene_version=1, scene_name="Not a robot model",
        objects=[object_(0, "table", "surface"),
                 object_(8, position=(10, 0, 0), scale=(1, 2, 3)),
                 object_(11, "apple", position=(-9, 0, 0), parent=8, support=0,
                         metadata_ref="$LIBRARY_SERVER/1"),
                 object_(12, "apple", position=(-2, 0, 0), metadata_ref="$LIBRARY_SERVER/1")])


def entity_(name="apple", category="fruit", **kwargs):
    return TaskEntity(entity_id=name, semantic_name=name, category=category, **kwargs)


def test_grounding_uses_instance_semantic_world_scale_and_numeric_reference():
    scene = scene_()
    relation = SpatialRelation(subject="apple", relation="nearest", reference="table")
    intent = TaskIntent(instruction="找最近的苹果", entities=[entity_(), entity_("table", "surface")],
                        operations=[], spatial_relations=[relation])
    task = SceneGrounder().ground(intent, scene)
    apple = task.entities[0]
    assert apple.scene_object_id == 11
    assert apple.scene_object_ids == [11]
    assert apple.metadata_ref == "$LIBRARY_SERVER/1"
    assert apple.model_scale == (1, 2, 3)
    assert relation.reference == "table"
    assert task.scene_id == 0
    assert "asset_id" not in apple.model_dump()


def test_global_alias_category_and_absent_semantic():
    scene = scene_()
    selector = SemanticEntitySelector(aliases={"苹果": "apple"}, category_aliases={"水果": "fruit"})
    entity = TaskEntity(entity_id="a", semantic_name="苹果", category="水果")
    assert [o.object_id_in_scene for o in selector.select("a", [entity], [], scene)] == [11, 12]
    entity = entity.model_copy(update={"semantic_name": "anything", "category_only": True})
    assert len(selector.select("a", [entity], [], scene)) == 2
    # Resource identity must not override an instance's semantic name.
    changed = scene.model_copy(deep=True)
    changed.objects[2].components[1].properties["semantic_name"] = "pear"
    entity = TaskEntity(entity_id="a", semantic_name="pear", category="fruit")
    assert selector.select("a", [entity], [], changed)[0].object_id_in_scene == 11


def test_color_cannot_be_inferred_from_display_or_renderer():
    scene = scene_()
    scene.objects[2].object_name_in_scene = "red apple"
    scene.objects[2].components.append(SceneComponent(component_type="MeshRenderer",
                                                      properties={"forceOverrideColor": "#FF0000"}))
    entity = entity_(color="red")
    with pytest.raises(ValueError, match="grounding_evidence_missing: color"):
        SemanticEntitySelector().select("apple", [entity], [], scene)


def test_on_uses_support_zero_inside_requires_evidence():
    scene = scene_()
    candidates = scene.objects[2:]
    resolver = SceneRelationResolver()
    assert [o.object_id_in_scene for o in resolver.resolve(candidates, [
        ResolvedSelectionRelation(relation="on", reference_object_id=0)], scene)] == [11]
    with pytest.raises(ValueError, match="scene_relation_evidence_missing: inside"):
        resolver.resolve(candidates, [ResolvedSelectionRelation(relation="inside", reference_object_id=0)], scene)
    with pytest.raises(TypeError, match="requires_resolved"):
        resolver.resolve(candidates, [SpatialRelation(subject="apple", relation="on", reference="table")], scene)


def test_world_halves_and_numeric_exclusion():
    scene = scene_()
    entity = entity_()
    selected = SemanticEntitySelector().select("apple", [entity],
        [SpatialRelation(subject="apple", relation="right")], scene)
    assert [o.object_id_in_scene for o in selected] == [11]
    entity = entity.model_copy(update={"exclude_scene_object_ids": [11]})
    assert [o.object_id_in_scene for o in SemanticEntitySelector().select("apple", [entity], [], scene)] == [12]


def test_query_world_position_state_and_json_roundtrip():
    scene = scene_()
    engine = SceneQueryEngine()
    query = SceneQueryIntent(query_type="position", entities=[entity_()], target="apple")
    result = engine.query(query, scene)
    assert result.positions[11] == (1, 0, 0)
    assert result.object_ids == [11, 12]
    assert type(result).model_validate_json(result.model_dump_json()) == result
    state = engine.query(query.model_copy(update={"query_type": "state"}), scene)
    assert state.states == {11: {"support": 0}, 12: {"support": None}}


def test_codec_team_fixture_and_legacy_rejection(tmp_path):
    source = Path(__file__).parent / "fixtures/shared_scene_v1.json"
    raw = json.loads(source.read_text())
    codec = SceneFileCodec()
    assert codec.payload(codec.load(source)) == raw
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"scene_id": "old", "objects": []}))
    with pytest.raises(BrainError, match="Expected shared"):
        codec.load(old)


def test_transform_patch_preserves_unrelated_components_and_clears_support():
    source = Path(__file__).parent / "fixtures/shared_scene_v1.json"
    scene = SceneFileCodec().load(source)
    scene.objects[0].components.append(SceneComponent(component_type="Sensor", properties={"opaque": [1, None]}))
    before = scene.model_dump(mode="json")
    manager = SceneManager(scene)
    transform = SceneIndex(scene).component(0, "Transform").model_copy(deep=True)
    transform.properties["position"] = [2, 3, 4]
    result = manager.apply_patch(ScenePatch(scene_id=1, base_scene_version=1, operations=[
        {"action": "upsert_component", "object_id_in_scene": 0, "component": transform}]))
    after = result.model_dump(mode="json")
    assert after["objects"][1:] == before["objects"][1:]
    expected = before["objects"][0]
    expected["components"][0]["properties"]["position"] = [2, 3, 4]
    expected["components"][3]["properties"]["support"] = None
    assert after["objects"][0] == expected
    assert result.scene_version == 2
    assert SceneIndex(result).transform(1).parent == 0
    assert SceneIndex(result).robot_driver(3) == SceneIndex(scene).robot_driver(3)


def test_patch_failure_atomic_and_deleted_ids_cannot_be_reused():
    scene = scene_()
    manager = SceneManager(scene)
    patch = ScenePatch(scene_id=0, base_scene_version=1, operations=[
        {"action": "remove_object", "object_id_in_scene": 12}])
    manager.apply_patch(patch)
    assert manager.seen_scene_object_ids == {0, 8, 11, 12}
    assert manager.next_scene_object_id == 13
    snapshot = manager.scene.model_dump()
    with pytest.raises(ValueError, match="id_reused"):
        manager.apply_patch(ScenePatch(scene_id=0, base_scene_version=2, operations=[
            {"action": "add_object", "object_id_in_scene": 12, "object": object_(12, "banana")}]))
    with pytest.raises(ValueError, match="parent_invalid"):
        manager.apply_patch(ScenePatch(scene_id=0, base_scene_version=2, operations=[
            {"action": "add_object", "object_id_in_scene": 13, "object": object_(13, "banana")},
            {"action": "remove_object", "object_id_in_scene": 8}]))
    assert manager.scene.model_dump() == snapshot
    assert 13 not in manager.seen_scene_object_ids
    assert manager.next_scene_object_id == 13


def test_identical_transform_does_not_discard_existing_support():
    scene = scene_()
    manager = SceneManager(scene)
    result = manager.apply_patch(ScenePatch(scene_id=0, base_scene_version=1, operations=[
        {"action": "upsert_component", "object_id_in_scene": 11,
         "component": SceneIndex(scene).component(11, "Transform")}]))
    assert SceneIndex(result).semantic(11).support == 0


@pytest.mark.parametrize("invalid", ["0", True, -1, 2**53])
def test_concrete_ids_strict_everywhere(invalid):
    for model, field, extra in [
        (LocateParameters, "target", {}),
        (CommandPlacementTarget, "reference", {"kind": "relative_object", "relation": "near"}),
        (ExecutionFeedback, "holding_object", {"request_id": "r", "status": "success", "commands": []}),
        (ResolvedSelectionRelation, "reference_object_id", {"relation": "on"}),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate({field: invalid, **extra})


def test_semantic_to_concrete_commands_keep_zero_and_config_robot():
    scene = scene_()
    scene.objects = [scene.objects[0], scene.objects[3]]
    intent = TaskIntent(instruction="放到桌上", entities=[entity_(), entity_("table", "surface")],
        operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="apple",
            destination="table", placement_target=PlacementTarget(kind="support_surface", reference="table"))])
    task = SceneGrounder().ground(intent, scene)
    task = TaskExpander().expand(task, scene)
    plan = RecipePlanner().plan(task)
    commands = CommandExporter(robot="configured-model").export("r", task, plan, scene)
    payload = canonical_commands(commands)
    assert payload["robot"] == "configured-model"
    assert payload["scene_id"] == 0
    assert payload["operations"][0]["placement_target"]["reference"] == 0
    assert any(command["parameters"].get("target") == 0 for command in payload["commands"])
    assert intent.operations[0].placement_target.reference == "table"
    assert isinstance(commands.operations[0].placement_target, CommandPlacementTarget)

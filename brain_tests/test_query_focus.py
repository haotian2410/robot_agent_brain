import pytest
from robot_agent_brain.contracts.scene import SceneConfig
from robot_agent_brain.contracts.spatial import SpatialRelation
from robot_agent_brain.scene.scene_graph import world_transform
from test_component_runtime import object_
from robot_agent_brain.contracts.turn import SceneQueryIntent, BrainTurn, SceneEditIntent, SceneEditPlan
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.session.brain_session import BrainSession


def scene():
    return SceneConfig(scene_schema_version=1, scene_version=0, scene_id=1, scene_name="s", objects=[
        object_(0, "apple", position=(-.3, 0, 0), metadata_ref="$DEMO_LIBRARY/2"),
        object_(1, "apple", position=(.3, 0, 0), metadata_ref="$DEMO_LIBRARY/2")])


def query(name="apple", kind="count", side=None):
    return SceneQueryIntent(query_type=kind, target="apple", entities=[
        TaskEntity(entity_id="apple", semantic_name=name, category="fruit")],
        relations=[SpatialRelation(subject="apple", relation=side)] if side else [])


def test_query_filters_world_relation_and_returns_ids_for_count():
    value = scene()
    before = value.model_dump()
    result = SceneQueryEngine().query(query(side="left"), value)
    assert result.count == 1 and result.object_ids == [0]
    assert value.model_dump() == before


def test_color_constraint_without_evidence_is_not_a_zero_count():
    value = query()
    value.entities[0].color = "red"
    with pytest.raises(ValueError, match="grounding_evidence_missing: color"):
        SceneQueryEngine().query(value, scene())


def test_zero_matches_and_no_scene_are_distinct():
    engine = SceneQueryEngine()
    assert engine.query(query("pear"), scene()).count == 0
    assert engine.query(query("pear", "existence"), scene()).exists is False
    assert engine.query(query("apple", "existence"), scene()).exists is True
    with pytest.raises(ValueError, match="scene_required"):
        engine.query(query(), None)


def test_query_and_edit_focus_then_delete_invalidation():
    pipeline = BrainPipeline(None, BrainConfig().load_assets())
    session = BrainSession(scene(), pipeline, MockScenePlatform())
    session.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="red?", scene_query=query(side="left")))
    assert session.dialogue.last_entity_id == 0
    session.process_turn("e", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="move",
        scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single', exclude_scene_object_ids=[0])], operations=[SceneEditIntent(operation='translate', direction='right', distance_m=0.1, target="target")])))
    assert session.dialogue.last_entity_id == 1
    assert "[dialogue_ref=apple]" in session.dialogue.contextualize("移动它", session.scene)
    session.process_turn("d", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="remove",
        scene_edit=SceneEditPlan(entities=[dict(entity_id="target", semantic_name='apple', category='fruit', count=1, quantity_mode='single', exclude_scene_object_ids=[0])], operations=[SceneEditIntent(operation='remove', target="target")])))
    assert session.dialogue.last_entity_id is None
    with pytest.raises(ValueError, match="dialogue_reference_missing"):
        session.dialogue.contextualize("抓起它", session.scene)


def test_collection_query_preserves_plural_focus():
    pipeline = BrainPipeline(None, BrainConfig().load_assets())
    dialogue = DialogueState()
    result = pipeline.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="apples?",
                                                  scene_query=SceneQueryIntent(query_type="count", target="apple", entities=[dict(entity_id="apple", semantic_name="apple", category="fruit")])), scene())
    dialogue.observe(result)
    assert dialogue.last_entity_ids == [0, 1]
    with pytest.raises(ValueError, match="dialogue_reference_ambiguous"):
        dialogue.contextualize("抓起它", scene())
    assert "dialogue_ref_set" in dialogue.contextualize("移动它们", scene())


def test_edit_collection_then_plural_edit_keeps_same_instances():
    session = BrainSession(scene(), BrainPipeline(None, BrainConfig().load_assets()), MockScenePlatform())
    first = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="两个苹果右移五厘米",
        scene_edit=SceneEditPlan(entities=[TaskEntity(entity_id="apples", semantic_name="apple", category="fruit", count=2, quantity_mode="all")],
            operations=[SceneEditIntent(operation="translate", target="apples", direction="right", distance_m=.05)]))
    session.process_turn("first", first)
    assert session.dialogue.last_entity_ids == [0, 1]
    assert "dialogue_ref_set" in session.dialogue.contextualize("把它们向前移动五厘米", session.scene)
    second = first.model_copy(deep=True)
    second.scene_edit.entities[0].dialogue_ref_set = True
    second.scene_edit.operations[0].direction = "front"
    result = session.process_turn("second", second)
    assert [op.object_id_in_scene for op in result.scene_patch.operations if op.component.component_type == "Transform"] == [0, 1]
    assert [world_transform(session.scene, o.object_id_in_scene).position for o in session.scene.objects] == [(-.25,.05,0),(.35,.05,0)]
    assert session.scene.scene_version == 2
    with pytest.raises(ValueError, match="dialogue_reference_ambiguous"):
        session.dialogue.contextualize("把它右移五厘米", session.scene)

import pytest
from robot_agent_brain.contracts.scene import SceneConfig, SceneObject, Transform
from robot_agent_brain.contracts.turn import SceneQueryIntent, BrainTurn, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.query import SceneQueryEngine
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.adapters.mock_scene_platform import MockScenePlatform
from robot_agent_brain.session.brain_session import BrainSession


def scene():
    return SceneConfig(scene_id="s", objects=[
        SceneObject(scene_object_id="a", asset_id="demo_apple", semantic_name="apple", category="fruit",
                    transform=Transform(position=(-.3,0,0)), properties={"color":"red"}),
        SceneObject(scene_object_id="b", asset_id="demo_apple", semantic_name="apple", category="fruit",
                    transform=Transform(position=(.3,0,0)), properties={"color":"green"})])


def query(color="red", kind="count"):
    return SceneQueryIntent(query_type=kind, target="apple", entities=[
        TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", color=color)])


def test_query_filters_color_and_returns_ids_for_count():
    value = scene()
    before = value.model_dump()
    result = SceneQueryEngine().query(query(), value)
    assert result.count == 1 and result.object_ids == ["a"]
    assert value.model_dump() == before


def test_zero_matches_and_no_scene_are_distinct():
    engine = SceneQueryEngine()
    assert engine.query(query("blue"), scene()).count == 0
    assert engine.query(query("blue", "existence"), scene()).exists is False
    assert engine.query(query("red", "existence"), scene()).exists is True
    with pytest.raises(ValueError, match="scene_required"):
        engine.query(query(), None)


def test_query_and_edit_focus_then_delete_invalidation():
    pipeline = BrainPipeline(None, BrainConfig().load_assets())
    session = BrainSession(scene(), pipeline, MockScenePlatform())
    session.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="red?", scene_query=query()))
    assert session.dialogue.last_entity_id == "a"
    session.process_turn("e", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="move",
        scene_edit=SceneEditIntent(operation="translate", semantic_name="b", category="fruit", direction="right", distance_m=.1)))
    assert session.dialogue.last_entity_id == "b"
    assert "dialogue_scene_object_id=b" in session.dialogue.contextualize("移动它", session.scene)
    session.process_turn("d", BrainTurn(status="accepted", turn_kind="scene_edit", instruction="remove",
        scene_edit=SceneEditIntent(operation="remove", semantic_name="b", category="fruit")))
    assert session.dialogue.last_entity_id is None
    with pytest.raises(ValueError, match="dialogue_reference_missing"):
        session.dialogue.contextualize("抓起它", session.scene)


def test_collection_query_preserves_plural_focus():
    pipeline = BrainPipeline(None, BrainConfig().load_assets())
    dialogue = DialogueState()
    result = pipeline.process_turn("q", BrainTurn(status="accepted", turn_kind="scene_query", instruction="apples?",
                                                  scene_query=SceneQueryIntent(query_type="count", semantic_name="apple")), scene())
    dialogue.observe(result)
    assert dialogue.last_entity_ids == ["a", "b"]
    with pytest.raises(ValueError, match="dialogue_reference_ambiguous"):
        dialogue.contextualize("抓起它", scene())
    assert "dialogue_ref_set" in dialogue.contextualize("移动它们", scene())

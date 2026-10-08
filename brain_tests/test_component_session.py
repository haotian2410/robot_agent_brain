from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.scene import ScenePatch, SceneSnapshot
from robot_agent_brain.contracts.task_intent import TaskIntent
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.models.task_understanding import ParseEntity
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.dialogue_state import DialogueState
from robot_agent_brain.session.store import SessionStore, SessionState
from test_component_runtime import scene_, object_, entity_


@pytest.mark.parametrize("history,next_id", [({True}, None), ({"1"}, None),
    ({-1}, None), ({2**53}, None), (set(), True), (set(), -1), (set(), 2**53 + 1)])
def test_direct_manager_rejects_invalid_identity_history(history, next_id):
    from robot_agent_brain.scene.scene_manager import SceneManager
    with pytest.raises(ValueError, match="scene_.*invalid"):
        SceneManager(scene_(), seen_scene_object_ids=history, next_scene_object_id=next_id)


def test_session_deleted_id_history_survives_checkpoint(tmp_path):
    session = BrainSession(scene_(), None, LocalScenePlatform())
    session.apply_scene_patch(ScenePatch(scene_id=0, base_scene_version=1, operations=[
        {"action": "remove_object", "object_id_in_scene": 12}]))
    session.dialogue = DialogueState(last_entity_id=0, last_entity_ids=[0])
    session.holding_object = 0
    store = SessionStore(tmp_path)
    with store.lock("session"):
        store.save("session", session, revision=1)
        state = store.load("session")
    assert state.seen_scene_object_ids == {0, 8, 11, 12}
    assert state.next_scene_object_id == 13
    resumed = store.restore(state, BrainSession(None, None, LocalScenePlatform()))
    assert resumed.holding_object == 0
    assert resumed.dialogue.last_entity_id == 0
    assert resumed.seen_scene_object_ids == state.seen_scene_object_ids
    assert resumed.next_scene_object_id == 13
    with pytest.raises(ValueError, match="id_reused"):
        resumed.apply_scene_patch(ScenePatch(scene_id=0, base_scene_version=2, operations=[
            {"action": "add_object", "object_id_in_scene": 12, "object": object_(12, "banana")}]))
    resumed.apply_scene_patch(ScenePatch(scene_id=0, base_scene_version=2, operations=[
        {"action": "add_object", "object_id_in_scene": 13, "object": object_(13, "banana")}]))
    assert resumed.next_scene_object_id == 14
    assert resumed.seen_scene_object_ids == {0, 8, 11, 12, 13}


@pytest.mark.parametrize("change", [
    {"seen_scene_object_ids": {0, 8, 11}}, {"next_scene_object_id": 12},
    {"next_scene_object_id": True}, {"holding_object": "0"},
    {"dialogue": {"last_entity_id": 99}},
])
def test_checkpoint_rejects_invalid_history_or_concrete_ids(change):
    values = dict(session_id="s", revision=1, scene=scene_(),
                  seen_scene_object_ids={0, 8, 11, 12}, next_scene_object_id=13)
    with pytest.raises(ValidationError):
        SessionState(**{**values, **change})


def test_failed_platform_patch_does_not_consume_identity():
    class RejectingPlatform(LocalScenePlatform):
        def apply_patch(self, patch):
            return SceneSnapshot(scene_id=0, scene_version=2, accepted=False, error="rejected")
    session = BrainSession(scene_(), None, RejectingPlatform())
    with pytest.raises(ValueError, match="rejected"):
        session.apply_scene_patch(ScenePatch(scene_id=0, base_scene_version=1, operations=[
            {"action": "add_object", "object_id_in_scene": 13, "object": object_(13, "banana")}]))
    assert session.scene.scene_version == 1
    assert session.next_scene_object_id == 13
    assert 13 not in session.seen_scene_object_ids
    assert session.sync_state == "unknown"


def test_held_zero_prevents_scene_patch():
    session = BrainSession(scene_(), None, LocalScenePlatform())
    session.holding_object = 0
    result = SimpleNamespace(commands=None, scene_patch=ScenePatch(scene_id=0, base_scene_version=1,
        operations=[{"action": "remove_object", "object_id_in_scene": 0}]))
    with pytest.raises(ValueError, match="held_object_conflict"):
        session._accept_result("r", result)
    assert session.scene.scene_version == 1


def test_dialogue_zero_semantic_marker_and_binding():
    scene = scene_()
    dialogue = DialogueState(last_entity_id=0, last_entity_ids=[0])
    text = dialogue.contextualize("定位它", scene)
    assert text == "定位它 [dialogue_ref=table]"
    task = TaskIntent(instruction="定位它", entities=[entity_("table", "surface", dialogue_ref=True)], operations=[])
    assert dialogue.bindings(task, scene) == {"table": [0]}
    assert dialogue.contextualize("另一个桌子", scene) == "另一个桌子 [dialogue_exclude=table]"


def test_another_exclusion_is_python_only_and_never_first_entity_guess():
    scene = scene_()
    dialogue = DialogueState(last_entity_id=11, last_entity_ids=[11])
    instruction = "把另一个苹果放到桌上"
    assert dialogue.contextualize(instruction, scene) == instruction + " [dialogue_exclude=apple]"
    turn = BrainTurn(status="accepted", turn_kind="robot_task", instruction=instruction,
        task_intent=TaskIntent(instruction=instruction,
            entities=[entity_("table", "surface"), entity_()], operations=[]))
    result = dialogue.apply_exclusions(turn, scene)
    assert result.task_intent.entities[0].exclude_scene_object_ids == []
    assert result.task_intent.entities[1].exclude_scene_object_ids == [11]
    assert turn.task_intent.entities[1].exclude_scene_object_ids == []
    assert "exclude_scene_object_ids" not in ParseEntity.model_json_schema()["properties"]


def test_scene_reload_cannot_resurrect_retired_id():
    scene = scene_()
    session = BrainSession(scene, None, LocalScenePlatform())
    session.apply_scene_patch(ScenePatch(scene_id=0, base_scene_version=1, operations=[
        {"action": "remove_object", "object_id_in_scene": 12}]))
    with pytest.raises(ValueError, match="id_reused"):
        session.initialize_scene(scene)
    assert session.scene.scene_version == 2

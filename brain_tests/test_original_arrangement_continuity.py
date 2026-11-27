import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.contracts.scene import parse_scene_document
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.original_scene_store import OriginalSceneStore
from robot_agent_brain.session.store import SessionStore
from test_layout_transaction import setup


def frozen_group(tmp_path):
    scene, base, editor = setup(.2)
    document = scene.raw_document()
    document["scene_name_Chinese"] = "布局原始快照"
    scene = parse_scene_document(document, uint32=False).view
    data = base.model_dump()
    data.update(pattern={"kind": "line", "axis": "x"})
    data["items"]["requested_count"] = 2
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="创建布局",
                     arrangement_spec=ArrangementSpec.model_validate(data))
    session = BrainSession(scene, BrainPipeline(None, editor.assets, scene_editor=editor), LocalScenePlatform())
    session.process_turn("seed", turn)
    session.original_store = OriginalSceneStore(tmp_path / "s")
    session.original_scene_manifest = session.original_store.capture_once(
        session.scene, platform_object_ids={0}, request_id="freeze", source="generated",
        arrangement_records=session.arrangement_index.snapshot())
    session.scene_reset_allowed = True
    return session, turn


@pytest.mark.parametrize("operation", ["append", "rearrange", "replace"])
def test_original_group_operations_use_frozen_members_after_restart(tmp_path, operation):
    session, turn = frozen_group(tmp_path)
    snapshot = (tmp_path / "s/original_scene.json").read_bytes()
    manifest = (tmp_path / "s/original_scene_manifest.json").read_bytes()
    original_ids = set(session.arrangement_index.get("arr-grid").slot_bindings.values())
    # Diverge current layout from original and verify restoration never uses
    # this current arrangement's positions or branch-specific identities.
    data = turn.arrangement_spec.model_dump()
    data.update(operation="rearrange")
    data["pattern"]["axis"] = "y"
    data["region"]["side"] = "right_half"
    session.process_turn("current-change", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    store = SessionStore(tmp_path)
    with store.lock("s"):
        store.save("s", session, revision=1)
    restored = store.restore(store.load("s"), BrainSession(None, session.pipeline, LocalScenePlatform()))
    restored.original_store = session.original_store
    restored.scene_reset_allowed = True
    data = turn.arrangement_spec.model_dump()
    data.update(operation=operation, basis="original")
    if operation == "append":
        data["items"]["requested_count"] = 1
        data["region"]["side"] = "left_half"
    elif operation == "replace":
        data["items"]["assets"][0]["alias"] = "banana"
    else:
        data["pattern"]["axis"] = "y"
    result = restored.process_turn("derive", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    members = result.layout_resolution.instance_ids
    assert len(members) == (3 if operation == "append" else 2)
    assert not original_ids.intersection(members)
    assert restored.scene.scene_id != session.scene.scene_id
    assert restored.scene.raw_document()["scene_name_Chinese"] == "布局原始快照"
    assert restored.arrangement_index.get("arr-grid").slot_bindings == result.layout_resolution.slot_bindings
    assert (tmp_path / "s/original_scene.json").read_bytes() == snapshot
    assert (tmp_path / "s/original_scene_manifest.json").read_bytes() == manifest
    index = SceneIndex(restored.scene)
    if operation == "append":
        positions = [index.transform(result.layout_resolution.slot_bindings[slot]).position for slot in ("s0", "s1")]
        assert sorted(round(p[0], 5) for p in positions) == [-.1, .1]
        assert all(p[1] == 0 for p in positions)
    if operation == "replace":
        assert all(index.semantic(oid).semantic_name == "banana" for oid in members)


def test_original_group_missing_does_not_fall_back_to_current(tmp_path):
    session, turn = frozen_group(tmp_path)
    record = session.arrangement_index.get("arr-grid").model_copy(update={"arrangement_id": "arr-current-only"})
    session.arrangement_index.put(record)
    data = turn.arrangement_spec.model_dump()
    data.update(arrangement_id="arr-current-only", operation="rearrange", basis="original")
    before = session.scene.raw_document()
    records = session.arrangement_index.snapshot()
    with pytest.raises(ValueError, match="scene_layout_arrangement_missing"):
        session.process_turn("missing", turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)}))
    assert session.scene.raw_document() == before
    assert session.arrangement_index.snapshot() == records


def test_original_understanding_context_is_frozen_and_request_scoped(tmp_path):
    session, turn = frozen_group(tmp_path)
    frozen = session.original_understanding_context()
    assert frozen["basis"] == "original"
    assert frozen["arrangements"][0]["arrangement_id"] == "arr-grid"
    session.arrangement_index.put(session.arrangement_index.get("arr-grid").model_copy(
        update={"arrangement_id": "arr-current-only"}))
    requests = []
    class Provider:
        def understand_turn(self, request):
            requests.append(request)
            return BrainTurn(status="clarification_required", turn_kind="scene_layout",
                             instruction=request.instruction, clarification_question="哪一组？")
    session.pipeline.understanding = Provider()
    session.pipeline.understand_turn("重排原始场景的布局", scene=session.scene,
        arrangement_index=session.arrangement_index,
        original_context=session.original_understanding_context())
    context = requests[0].scene_context
    assert len(context["arrangements"]) == 2
    assert context["original_snapshot"] == frozen
    context["original_snapshot"]["arrangements"].clear()
    assert session.original_understanding_context() == frozen
    session.pipeline.understand_turn("其他会话", scene=session.scene)
    assert "original_snapshot" not in requests[1].scene_context

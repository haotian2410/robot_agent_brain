import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.session.store import SessionState, SessionStore
from test_layout_transaction import original_layout_session


def test_failed_reservation_is_durable_before_candidate_and_not_reused(tmp_path):
    session, original_turn = original_layout_session(tmp_path / "durable", spacing=2)
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": "current"})})
    store = SessionStore(tmp_path)
    session.persist_identity_reservation = lambda: store.save("durable", session, revision=1)
    before = session.scene.raw_document()
    start = session.next_scene_object_id
    with store.lock("durable"):
        with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
            session.process_turn("bad", turn)
    # No post-error save: simulate losing the process immediately after its
    # write-ahead checkpoint. Restore must burn all reserved identities.
    state = store.load("durable")
    assert state.scene.raw_document() == before
    assert state.layout_id_reservations["bad"] == (start, start + 6)
    resumed = store.restore(state, BrainSession(None, session.pipeline, LocalScenePlatform()))
    assert resumed.seen_scene_object_ids >= set(range(start, start + 6))
    with pytest.raises(ValueError, match="scene_layout_request_reserved"):
        resumed.process_turn("bad", turn)
    spec = turn.arrangement_spec.model_dump()
    spec["spacing"]["value_m"] = .12
    result = resumed.process_turn("new", turn.model_copy(update={
        "arrangement_spec": ArrangementSpec.model_validate(spec)}))
    assert min(result.layout_resolution.instance_ids) >= start + 6
    assert resumed.scene.scene_version == state.scene.scene_version + 1


def test_checkpoint_failure_stops_before_layout_construction(tmp_path, monkeypatch):
    session, original_turn = original_layout_session(tmp_path)
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": "current"})})
    before = session.scene.raw_document()

    def unavailable():
        raise OSError("checkpoint_disk_unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("candidate must not be built without durable reservation")

    session.persist_identity_reservation = unavailable
    monkeypatch.setattr(session.pipeline.scene_editor, "layout_result", forbidden)
    with pytest.raises(OSError, match="checkpoint_disk_unavailable"):
        session.process_turn("disk-error", turn)
    assert session.scene.raw_document() == before
    assert not session.arrangement_index.snapshot()


def test_gateway_rejection_keeps_scene_but_burns_reserved_ids(tmp_path, monkeypatch):
    from robot_agent_brain.errors import SceneCommitRejected
    session, original_turn = original_layout_session(tmp_path)
    turn = original_turn.model_copy(update={"arrangement_spec":
        original_turn.arrangement_spec.model_copy(update={"basis": "current"})})
    before, start = session.scene.raw_document(), session.next_scene_object_id

    def reject(*args, **kwargs):
        raise SceneCommitRejected("gateway_refused")

    monkeypatch.setattr(session.platform, "apply_patch", reject)
    with pytest.raises(SceneCommitRejected):
        session.process_turn("refused", turn)
    assert session.scene.raw_document() == before
    assert session.next_scene_object_id == start + 6
    assert set(range(start, start + 6)) <= session.seen_scene_object_ids
    assert not session.arrangement_index.snapshot()
    assert not session.layout_request_receipts
    assert session.sync_state == "synchronized"


@pytest.mark.parametrize("ranges", [
    {"x": [True, 3]}, {"x": ["1", 3]}, {"x": [3, 3]},
    {"x": [1, 1002]}, {"x": [1, 3], "y": [2, 4]}, {"x": [1, 5000]},
])
def test_corrupt_reservation_ranges_rejected(ranges):
    with pytest.raises(ValueError):
        SessionState(session_id="bad", revision=1, next_scene_object_id=2000,
                     layout_id_reservations=ranges)

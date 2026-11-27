import pytest
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.planning.layout_quantity import quantity_candidates
from robot_agent_brain.session.brain_session import BrainSession
from test_layout_transaction import setup


def fixture(minimum=2, maximum=10):
    scene, base, editor = setup(.3)
    data = base.model_dump()
    data["pattern"] = {"kind": "line"}
    data["items"].update(requested_count=10, count_mode="auto", auto_count=True,
                         min_count=minimum, max_count=maximum)
    spec = ArrangementSpec.model_validate(data)
    session = BrainSession(scene, BrainPipeline(None, editor.assets, scene_editor=editor), LocalScenePlatform())
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="允许2到10个自动安排",
                     arrangement_spec=spec)
    return session, turn


def test_auto_range_real_geometry_commits_actual_members_once_and_replays():
    session, turn = fixture()
    before = session.scene.scene_version
    result = session.process_turn("range", turn)
    count = len(result.layout_resolution.instance_ids)
    assert 2 <= count < 10
    assert len(result.layout_plan.slots) == count
    assert len(session.arrangement_index.get(turn.arrangement_spec.arrangement_id).slot_bindings) == count
    assert session.scene.scene_version == before + 1
    assert "layout_count_adjustment=authorized_range" in result.assumptions
    start, end = session.layout_id_reservations["range"]
    assert end - start == 10
    assert session.next_scene_object_id >= end
    assert f"layout_count_resolved={count}" in result.assumptions
    assert result.layout_resolution.assumptions == result.assumptions
    assert result.layout_resolution.adjusted_spacing_m is None  # fixed .3m was not adjusted
    current = session.scene.raw_document()
    assert session.process_turn("range", turn) == result
    assert session.scene.raw_document() == current
    assert not session.exported_commands


def test_infeasible_authorized_range_never_drops_below_minimum_or_commits():
    session, turn = fixture(9, 10)
    before = session.scene.raw_document()
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        session.process_turn("too-many", turn)
    assert session.scene.raw_document() == before
    assert not session.arrangement_index.snapshot()
    assert not session.layout_request_receipts
    assert session.layout_id_reservations  # failed candidates cannot recycle IDs


def test_exact_or_unbounded_legacy_auto_never_changes_quantity():
    _, turn = fixture()
    data = turn.arrangement_spec.model_dump()
    for mode in ("exact", "auto"):
        data["items"].update(count_mode=mode, min_count=None, max_count=None)
        value = ArrangementSpec.model_validate(data)
        assert list(quantity_candidates(value)) == [value]


def test_quantity_search_does_not_reallocate_declared_mixed_assets_or_delete_members():
    _, turn = fixture()
    data = turn.arrangement_spec.model_dump()
    data["items"].update(mode="counts", assets=[{"alias": "apple", "count": 5}, {"alias": "banana", "count": 5}])
    spec = ArrangementSpec.model_validate(data)
    assert list(quantity_candidates(spec)) == [spec]
    for operation in ("rearrange", "replace"):
        value = turn.arrangement_spec.model_copy(update={"operation": operation})
        assert list(quantity_candidates(value)) == [value]


def test_candidate_order_is_nearest_first_and_deterministic():
    _, turn = fixture()
    data = turn.arrangement_spec.model_dump()
    data["items"]["requested_count"] = 6
    spec = ArrangementSpec.model_validate(data)
    assert [v.items.requested_count for v in quantity_candidates(spec)] == [6, 5, 7, 4, 8, 3, 9, 2, 10]


def test_append_quantity_search_preserves_existing_members_and_burns_reserved_tail():
    session, turn = fixture()
    initial = turn.arrangement_spec.model_dump()
    initial["items"].update(requested_count=1, count_mode="exact", auto_count=False,
                            min_count=None, max_count=None)
    initial["region"]["side"] = "left_half"
    first = session.process_turn("initial", turn.model_copy(update={
        "arrangement_spec": ArrangementSpec.model_validate(initial)}))
    before = {o.object_id_in_scene: o.model_dump() for o in session.scene.objects}
    version = session.scene.scene_version
    data = turn.arrangement_spec.model_dump()
    data["operation"] = "append"
    data["region"]["side"] = "right_half"
    data["pattern"] = {"kind": "line", "axis": "y"}
    append = turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    result = session.process_turn("append-auto", append)
    new_ids = set(result.layout_resolution.instance_ids) - set(first.layout_resolution.instance_ids)
    assert 2 <= len(new_ids) < 10
    assert session.scene.scene_version == version + 1
    assert first.layout_resolution.slot_bindings.items() <= result.layout_resolution.slot_bindings.items()
    for obj in session.scene.objects:
        if obj.object_id_in_scene in before:
            assert obj.model_dump() == before[obj.object_id_in_scene]
    start, end = session.layout_id_reservations["append-auto"]
    assert end - start == 10
    assert session.next_scene_object_id >= end
    assert all(start <= oid < end for oid in new_ids)
    snapshot = session.scene.raw_document()
    assert session.process_turn("append-auto", append) == result
    assert session.scene.raw_document() == snapshot


@pytest.mark.parametrize("message", ["asset_missing: apple", "scene_layout_asset_ambiguous",
                                    "scene_layout_region_unresolved"])
def test_non_geometry_errors_do_not_trigger_quantity_retry(monkeypatch, message):
    session, turn = fixture()
    before = session.scene.raw_document()
    calls = []
    def reject(spec, *args, **kwargs):
        calls.append(spec.items.requested_count)
        raise ValueError(message)
    monkeypatch.setattr(session.pipeline.scene_editor, "layout_result", reject)
    with pytest.raises(ValueError, match=message):
        session.process_turn("invalid-asset", turn)
    assert calls == [10]
    assert session.scene.raw_document() == before
    assert not session.arrangement_index.snapshot()
    assert not session.layout_request_receipts


def test_failed_append_preserves_members_receipts_and_allocates_fresh_ids_next_time():
    session, turn = fixture()
    initial = turn.arrangement_spec.model_dump()
    initial["items"].update(requested_count=1, count_mode="exact", auto_count=False,
                            min_count=None, max_count=None)
    initial["region"]["side"] = "left_half"
    session.process_turn("initial", turn.model_copy(update={
        "arrangement_spec": ArrangementSpec.model_validate(initial)}))
    before = session.scene.raw_document()
    members = session.arrangement_index.snapshot()
    receipts = dict(session.layout_request_receipts)
    data = turn.arrangement_spec.model_dump()
    data["operation"] = "append"
    data["items"]["min_count"] = 9
    data["region"]["side"] = "right_half"
    append = turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    with pytest.raises(ValueError, match="scene_layout_capacity_exceeded"):
        session.process_turn("append-impossible", append)
    assert session.scene.raw_document() == before
    assert session.arrangement_index.snapshot() == members
    assert session.layout_request_receipts == receipts
    _, burned_end = session.layout_id_reservations["append-impossible"]
    data["items"].update(requested_count=1, count_mode="exact", auto_count=False,
                         min_count=None, max_count=None)
    accepted = session.process_turn("append-valid", turn.model_copy(update={
        "arrangement_spec": ArrangementSpec.model_validate(data)}))
    new_ids = set(accepted.layout_resolution.instance_ids) - set(
        oid for record in members for oid in record["slot_bindings"].values())
    assert new_ids and min(new_ids) >= burned_end

"""Simulated feedback boundary, not proof of physical control execution."""
import pytest

from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.contracts.commands import ExecutionFeedback
from robot_agent_brain.contracts.scene import parse_scene_document
from robot_agent_brain.scene.component_access import SceneIndex
from test_layout_transaction import original_layout_session


@pytest.mark.parametrize("deleted", [False, True])
def test_feedback_then_append_uses_current_scene_not_cached_positions(tmp_path, deleted):
    session, turn = original_layout_session(tmp_path)
    turn = turn.model_copy(update={"arrangement_spec": turn.arrangement_spec.model_copy(update={"basis": "current"})})
    first = session.process_turn("create", turn)
    oid = first.layout_resolution.instance_ids[0]
    previous_record = session.arrangement_index.snapshot()
    document = session.scene.raw_document()
    document["scene_name_Chinese"] = "执行后布局"
    document["scene_version"] += 1
    if deleted:
        document["objects"] = [o for o in document["objects"] if o["object_id_in_scene"] != oid]
    else:
        obj = next(o for o in document["objects"] if o["object_id_in_scene"] == oid)
        transform = next(c for c in obj["components"] if c["component_type"] == "Transform")
        transform["properties"]["position"][1] -= .2
    confirmed = parse_scene_document(document, uint32=False).view
    session.pending_execution_request = "control-test"
    session.pending_commands = {"schema_version": "2.0", "commands": [{"command_id": "c1"}]}
    session.apply_execution_feedback(ExecutionFeedback(request_id="control-test", status="success",
        commands=[{"command_id": "c1", "status": "success"}]),
        confirmed_scene=confirmed, feedback_source="simulated")
    assert session.scene.raw_document()["scene_name_Chinese"] == "执行后布局"
    assert session.arrangement_index.snapshot() == previous_record
    data = turn.arrangement_spec.model_dump()
    data.update(operation="append", pattern={"kind": "grid", "rows": 1, "cols": 1})
    data["items"]["requested_count"] = 1
    data["region"]["side"] = "right_half"
    append = turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    before = session.scene.raw_document()
    if deleted:
        next_id = session.next_scene_object_id
        with pytest.raises(ValueError, match="scene_layout_arrangement_members_missing"):
            session.process_turn("append", append)
        assert session.scene.raw_document() == before
        assert session.next_scene_object_id == next_id
        return
    result = session.process_turn("append", append)
    slot = next(s for s, value in first.layout_resolution.slot_bindings.items() if value == oid)
    actual = tuple(SceneIndex(confirmed).transform(oid).position[:2])
    assert result.layout_resolution.world_positions[slot] == actual
    assert actual != first.layout_resolution.world_positions[slot]
    assert SceneIndex(session.scene).object(oid) == SceneIndex(confirmed).object(oid)
    assert session.scene.scene_version == confirmed.scene_version + 1

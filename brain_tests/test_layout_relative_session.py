import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.scene.geometry import world_bounds
from robot_agent_brain.scene.scene_graph import world_transform
from robot_agent_brain.session.brain_session import BrainSession
from test_layout_transaction import setup, supported_scene


def relative_session(side, axis, **region):
    scene = supported_scene()
    scene = scene.model_copy(update={"objects": scene.objects[:2]})
    _, base, editor = setup()
    data = base.model_dump()
    data["pattern"] = {"kind": "line", "axis": "y" if axis == 0 else "x"}
    data["items"]["requested_count"] = 2
    data["region"].update(kind="relative", anchor_ref="apple", side=side, **region)
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="相对锚点排列",
                     arrangement_spec=ArrangementSpec.model_validate(data))
    session = BrainSession(scene, BrainPipeline(None, editor.assets, scene_editor=editor),
                           LocalScenePlatform())
    return session, turn, editor


@pytest.mark.parametrize("side,axis,positive", [
    ("left_half", 0, False), ("right_half", 0, True),
    ("front_half", 1, True), ("back_half", 1, False),
])
def test_relative_layout_runs_through_pipeline_and_commits_once(side, axis, positive):
    session, turn, editor = relative_session(side, axis)
    before = session.scene.model_copy(deep=True)
    result = session.process_turn("relative", turn)
    assert session.scene.scene_version == before.scene_version + 1
    assert len(result.layout_resolution.instance_ids) == 2
    assert session.scene.objects[:2] == before.objects
    facts = editor._facts(None)
    anchor = before.objects[1]
    lo, hi = world_bounds(facts.asset(anchor, before), world_transform(before, anchor.object_id_in_scene))
    for oid in result.layout_resolution.instance_ids:
        obj = SceneIndex(session.scene).object(oid)
        low, high = world_bounds(facts.asset(obj, session.scene), world_transform(session.scene, oid))
        if positive:
            assert low[axis] >= hi[axis] + turn.arrangement_spec.constraints.min_clearance_m
        else:
            assert high[axis] <= lo[axis] - turn.arrangement_spec.constraints.min_clearance_m
        assert facts.footprint_contains(obj, before.objects[0], session.scene)
    assert session.arrangement_index.get(turn.arrangement_spec.arrangement_id).slot_bindings == result.layout_resolution.slot_bindings
    assert session.process_turn("relative", turn) == result
    assert session.scene.scene_version == before.scene_version + 1


@pytest.mark.parametrize("region,error", [
    ({"anchor_ref": "missing"}, "scene_layout_region_unresolved"),
    ({"surface_ref": "missing"}, "scene_layout_region_unresolved"),
    ({"width_m": 10}, "scene_layout_capacity_exceeded"),
])
def test_relative_layout_failure_does_not_publish(region, error):
    session, turn, _ = relative_session("left_half", 0)
    data = turn.arrangement_spec.model_dump()
    data["region"].update(region)
    turn = turn.model_copy(update={"arrangement_spec": ArrangementSpec.model_validate(data)})
    before = session.scene.raw_document()
    with pytest.raises(ValueError, match=error):
        session.process_turn("refused", turn)
    assert session.scene.raw_document() == before
    assert not session.arrangement_index.snapshot()
    assert not session.layout_request_receipts
    assert not session.exported_commands
    if error == "scene_layout_region_unresolved":
        assert not session.layout_id_reservations

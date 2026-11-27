"""Concurrent private candidates on a shared pipeline must remain session-local."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from robot_agent_brain.contracts.arrangement import ArrangementSpec
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.pipeline import BrainPipeline
from robot_agent_brain.scene.component_access import SceneIndex
from robot_agent_brain.session.brain_session import BrainSession
from robot_agent_brain.web.protocol import digest
from test_layout_transaction import setup


@pytest.mark.parametrize("second_fails", [False, True])
def test_shared_pipeline_concurrent_layout_identity_and_failure_isolation(monkeypatch, second_fails):
    scene, base, editor = setup()
    pipeline = BrainPipeline(None, editor.assets, scene_editor=editor)
    sessions = [BrainSession(scene.model_copy(deep=True, update={"scene_id": sid}), pipeline,
                             LocalScenePlatform()) for sid in (101, 202)]
    turns = []
    for count, axis in ((2, "x"), (3, "y")):
        data = base.model_dump()
        # Deliberately reuse arrangement and request names across sessions.
        data["pattern"] = {"kind": "line", "axis": axis}
        data["items"]["requested_count"] = count
        if count == 3 and second_fails:
            data["spacing"]["value_m"] = 10
        turns.append(BrainTurn(status="accepted", turn_kind="scene_layout",
                               instruction="独立会话布局", arrangement_spec=ArrangementSpec.model_validate(data)))
    originals = [s.scene.raw_document() for s in sessions]
    versions = [s.scene.scene_version for s in sessions]
    barrier = Barrier(2, timeout=10)
    original_resolve = editor.layout_result

    def synchronized_resolve(*args, **kwargs):
        barrier.wait()
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(editor, "layout_result", synchronized_resolve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(s.process_turn, "shared-request", turn)
                   for s, turn in zip(sessions, turns)]
        first = futures[0].result(timeout=20)
        if second_fails:
            with pytest.raises(ValueError, match="scene_layout_(capacity_exceeded|workspace_exceeded|collision)"):
                futures[1].result(timeout=20)
            assert sessions[1].scene.raw_document() == originals[1]
            assert not sessions[1].arrangement_index.snapshot()
            assert not sessions[1].layout_request_receipts
        else:
            second = futures[1].result(timeout=20)
            assert second.layout_resolution.scene_id == 202
            assert len(second.layout_resolution.instance_ids) == 3
            assert sessions[1].scene.scene_version == versions[1] + 1
            assert second.layout_resolution.slot_bindings != first.layout_resolution.slot_bindings
            assert len({SceneIndex(sessions[1].scene).transform(oid).position[1]
                        for oid in second.layout_resolution.instance_ids}) == 3
    monkeypatch.setattr(editor, "layout_result", original_resolve)
    assert first.layout_resolution.scene_id == 101
    assert len(first.layout_resolution.instance_ids) == 2
    assert sessions[0].scene.scene_version == versions[0] + 1
    assert len({SceneIndex(sessions[0].scene).transform(oid).position[0]
                for oid in first.layout_resolution.instance_ids}) == 2
    assert digest(sessions[0].scene) != digest(sessions[1].scene)
    before_replay = [digest(s.scene) for s in sessions]
    assert sessions[0].process_turn("shared-request", turns[0]) == first
    assert [digest(s.scene) for s in sessions] == before_replay
    assert not any(s.exported_commands for s in sessions)

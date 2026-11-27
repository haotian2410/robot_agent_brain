"""Process-recreation recovery tests with explicit uncertain platform evidence.

These use a platform double, not a claim of real Gateway crash testing.
"""
import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn
from test_application_artifacts import Provider
from test_layout_bootstrap_atomicity import CountingPlatform
from test_layout_transaction import setup


@pytest.mark.parametrize("applied_before_timeout", [False, True])
def test_uncertain_layout_publication_stays_unknown_after_application_restart(tmp_path, applied_before_timeout):
    scene, spec, _ = setup(.12)
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="新增六个苹果排成两行三列",
                     arrangement_spec=spec)
    class UncertainPlatform(CountingPlatform):
        def apply_patch(self, patch):
            if applied_before_timeout:
                super().apply_patch(patch)
            raise TimeoutError("gateway_acknowledgement_lost")

    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path))
    first = BrainApplication(config, provider=Provider(turn), platform_factory=UncertainPlatform)
    session = first.get_session("uncertain-layout")
    session.initialize_scene(scene)
    before = session.scene.raw_document()
    report = first.handle(turn.instruction, session_id="uncertain-layout")
    assert report.run_status != "success"
    assert session.sync_state == "unknown"
    assert report.scene_commit_status == "unknown"
    assert not session.layout_request_receipts
    assert not session.arrangement_index.snapshot()
    reserved_end = session.next_scene_object_id
    assert reserved_end > max(o.object_id_in_scene for o in scene.objects) + 1

    # New app and new platform instance: the persisted uncertainty, rather than
    # the old Python object or old platform state, must stop another layout.
    platform = CountingPlatform()
    second = BrainApplication(config, provider=Provider(turn), platform_factory=lambda: platform)
    restored = second.get_session("uncertain-layout")
    assert restored.sync_state == "unknown"
    assert restored.scene.raw_document() == before
    assert restored.next_scene_object_id == reserved_end
    calls_before = platform.loads, platform.patches
    retry = second.handle(turn.instruction, session_id="uncertain-layout")
    assert retry.error.code == "scene_sync_unknown"
    assert retry.scene_commit_status == "unknown"
    assert (platform.loads, platform.patches) == calls_before
    assert restored.scene.raw_document() == before
    assert restored.next_scene_object_id == reserved_end
    assert not restored.layout_request_receipts
    assert not restored.arrangement_index.snapshot()
    assert "commands" not in retry.artifacts

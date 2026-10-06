import json
import pytest
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.commands import CommandsFile
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.session.store import SessionStore
from test_application_artifacts import Provider, robot


def application(path, turn=None):
    return BrainApplication(BrainConfig(provider="replay", output_dir=str(path)), provider=Provider(turn or robot()))


def test_restore_scene_focus_export_and_pause(tmp_path):
    app = application(tmp_path)
    first = app.handle("two apples", session_id="restore")
    session = app.get_session("restore")
    original = session.scene.model_dump()
    focus = session.dialogue.model_dump()
    app.provider.turn = BrainTurn(status="accepted", turn_kind="session_control", instruction="pause",
                                 session_control={"action":"pause"})
    assert app.handle("pause", session_id="restore").run_status == "success"
    other = application(tmp_path)
    restored = other.get_session("restore")
    assert restored.scene.model_dump() == original
    assert restored.dialogue.model_dump() == focus
    assert restored.session_action == "pause"
    assert restored.last_exported_request == first.request_id
    assert restored.pending_execution_request is None
    assert other.handle("two apples", session_id="restore").error.code == "session_paused"


def test_pending_survives_restart_and_blocks_replacement(tmp_path):
    app = application(tmp_path)
    report = app.handle("two apples", session_id="pending")
    commands = CommandsFile.model_validate_json(open(report.artifacts["commands"]).read())
    app.mark_dispatched("pending", commands)
    other = application(tmp_path)
    assert other.get_session("pending").pending_execution_request == report.request_id
    assert other.handle("again", session_id="pending").error.code == "execution_pending"
    with pytest.raises(ValueError, match="execution_pending"):
        other.load_scene("pending", report.artifacts["scene_config"])


def test_failed_feedback_without_snapshot_restores_unknown(tmp_path):
    from robot_agent_brain.contracts.commands import ExecutionFeedback
    app = application(tmp_path)
    report = app.handle("two apples", session_id="feedback")
    commands = CommandsFile.model_validate_json(open(report.artifacts["commands"]).read())
    app.mark_dispatched("feedback", commands)
    feedback = ExecutionFeedback(request_id=report.request_id, status="failed", commands=[])
    app.apply_execution_feedback("feedback", feedback, feedback_source="simulated")
    restored = application(tmp_path).get_session("feedback")
    assert restored.sync_state == "unknown" and restored.pending_execution_request is None
    assert restored.last_feedback_source == "simulated"


def test_independent_app_refreshes_newer_checkpoint(tmp_path):
    first, second = application(tmp_path), application(tmp_path)
    first.handle("two apples", session_id="shared")
    second.get_session("shared")
    first.provider.turn = BrainTurn(status="accepted", turn_kind="session_control", instruction="pause",
                                   session_control={"action":"pause"})
    first.handle("pause", session_id="shared")
    assert second.get_session("shared").session_action == "pause"
    assert second.get_session("independent").scene is None


def test_lock_prevents_concurrent_session_mutation(tmp_path):
    first, second = SessionStore(tmp_path), SessionStore(tmp_path)
    with first.lock("locked"):
        with pytest.raises(ValueError, match="session_busy"):
            with second.lock("locked"):
                pass
        with second.lock("independent"):
            pass
    with second.lock("locked"):
        pass


def test_corrupt_state_never_silently_starts_fresh(tmp_path):
    app = application(tmp_path)
    app.handle("two apples", session_id="broken")
    path = tmp_path / "broken" / "session_state.json"
    payload = json.loads(path.read_text())
    payload["holding_object"] = "nonexistent"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="session_state_unknown_object"):
        application(tmp_path).get_session("broken")


def test_store_rejects_path_escape_and_symlinks(tmp_path):
    store = SessionStore(tmp_path / "out")
    with pytest.raises(ValueError, match="unsafe"):
        store.load("../bad")
    target = tmp_path / "external"
    target.mkdir()
    store.root.mkdir()
    (store.root / "alias").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="session_path_escape"):
        store.load("alias")

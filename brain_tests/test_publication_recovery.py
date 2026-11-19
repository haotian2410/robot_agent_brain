import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from test_application_artifacts import Provider, robot


def test_committed_scene_is_queryable_after_artifact_publication_failure(tmp_path, monkeypatch):
    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path))
    app = BrainApplication(config, provider=Provider(robot()))
    def fail(*args, **kwargs):
        raise OSError("simulated output failure")
    monkeypatch.setattr(app.writer, "publish", fail)
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "failed" and report.scene_commit_status == "committed"
    restored = BrainApplication(config, provider=Provider(robot()))
    record = restored.get_publication_status(report.session_id, report.request_id)
    assert record["scene_commit_status"] == "committed"
    assert record["request_id"] == report.request_id
    assert record["snapshot_id"] and record["publication_status"] == "failed"
    state = restored.store.load(report.session_id)
    assert state.scene.scene_id == report.scene_id
    baseline = (tmp_path / report.session_id / "original_scene.json").read_bytes()
    assert restored.handle("把两个苹果放进篮子", session_id=report.session_id).run_status == "success"
    assert (tmp_path / report.session_id / "original_scene.json").read_bytes() == baseline


def test_checkpoint_failure_records_commit_and_blocks_stale_restore(tmp_path, monkeypatch):
    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path))
    app = BrainApplication(config, provider=Provider(robot()))
    def fail(*args, **kwargs):
        raise OSError("checkpoint failed")
    monkeypatch.setattr(app, "_save_session", fail)
    report = app.handle("把两个苹果放进篮子")
    assert report.scene_commit_status == "committed"
    assert report.error.code == "artifact_write_failed"
    assert report.metrics["conversation_persistence_error"]["stage"] == "conversation_persistence"
    restored = BrainApplication(config, provider=Provider(robot()))
    record = restored.get_publication_status(report.session_id, report.request_id)
    assert record["scene_commit_status"] == "committed"
    with pytest.raises(ValueError, match="publication_recovery_required"):
        restored.get_session(report.session_id)


def test_conversation_failure_preserves_published_request_and_scene(tmp_path, monkeypatch):
    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path))
    app = BrainApplication(config, provider=Provider(robot()))
    published = []
    publish = app.writer.publish

    def remember(report, **kwargs):
        result = publish(report, **kwargs)
        published.append((result.request_id, result.scene_id, result.scene_version))
        return result

    def fail(*args, **kwargs):
        raise OSError("conversation journal unavailable")

    monkeypatch.setattr(app.writer, "publish", remember)
    monkeypatch.setattr(app, "_record_cli_turn", fail)
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "failed"
    assert report.scene_commit_status == "committed"
    assert (report.request_id, report.scene_id, report.scene_version) == published[0]
    assert report.error.stage == "conversation_persistence"
    assert report.executed is False
    record = app.get_publication_status(report.session_id, report.request_id)
    assert record["publication_status"] == "published"
    assert record["scene_commit_status"] == "committed"

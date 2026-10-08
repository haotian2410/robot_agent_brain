from pathlib import Path
import pytest
from robot_agent_brain.adapters.artifact_writer import ArtifactWriter
from robot_agent_brain.contracts.run_report import BrainRunReport
from robot_agent_brain.contracts.scene import SceneConfig


def report():
    return BrainRunReport(session_id="session1", request_id="r1", run_status="success", provider="replay")


def test_publishes_real_paths_and_never_overwrites(tmp_path):
    writer = ArtifactWriter(tmp_path)
    result = writer.publish(report(), scene=SceneConfig(scene_schema_version=1, scene_id=1, scene_version=0, scene_name="s", objects=[]))
    assert Path(result.artifacts["scene_config"]).is_file()
    assert Path(result.artifacts["scene_config"]).is_absolute()
    before = Path(result.artifacts["scene_config"]).read_bytes()
    with pytest.raises(ValueError, match="already_exists"):
        writer.publish(report(), scene=SceneConfig(scene_schema_version=1, scene_id=2, scene_version=0, scene_name="different", objects=[]))
    assert Path(result.artifacts["scene_config"]).read_bytes() == before


def test_no_old_artifact_paths_leak_into_failure(tmp_path):
    value = report().model_copy(update={"run_status":"failed", "artifacts":{"commands":"old.json"}})
    result = ArtifactWriter(tmp_path).publish(value)
    assert result.artifacts == {}


def test_traversal_and_failed_publish_cleanup(tmp_path, monkeypatch):
    writer = ArtifactWriter(tmp_path)
    with pytest.raises(ValueError, match="unsafe"):
        writer.publish(report().model_copy(update={"session_id":"../escape"}))
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(writer, "_write", fail)
    with pytest.raises(OSError):
        writer.publish(report())
    assert list((tmp_path / "session1").iterdir()) == []

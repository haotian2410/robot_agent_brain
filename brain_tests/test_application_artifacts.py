import json
import pytest
from pathlib import Path
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneQueryIntent, SceneEditIntent
from robot_agent_brain.contracts.task_intent import TaskIntent, TaskEntity, Operation
from robot_agent_brain.contracts.scene import SceneConfig


class Provider:
    def __init__(self, turn):
        self.turn, self.count = turn, 0
    def understand_turn(self, request):
        self.count += 1
        return self.turn


def robot():
    return BrainTurn(status="accepted", turn_kind="robot_task", instruction="test", task_intent=TaskIntent(
        instruction="test", entities=[TaskEntity(entity_id="a", semantic_name="apple", category="fruit", count=2, quantity_mode="all"),
                                       TaskEntity(entity_id="b", semantic_name="basket", category="container")],
        operations=[Operation(operation_id="op-1", task_type="pick_and_place", source="a", destination="b",
                              placement_target={"kind":"container_interior","reference":"b","relation":"inside"})]))


def test_no_scene_robot_publishes_matching_snapshot_and_commands(tmp_path):
    provider = Provider(robot())
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=provider)
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "success", report
    assert provider.count == 1
    assert report.scene_source == "generated" and report.executed is False
    scene = json.loads(Path(report.artifacts["scene_config"]).read_text())
    commands = json.loads(Path(report.artifacts["commands"]).read_text())
    assert (commands["scene_id"],commands["scene_version"]) == (scene["scene_id"],scene["scene_version"])
    assert len([o for o in scene["objects"] if o["semantic_name"] == "apple"]) == 2
    second = app.handle("重复任务", session_id=report.session_id)
    assert second.scene_source == "session" and second.scene_id == report.scene_id
    assert second.run_status == "success"


def test_no_scene_query_blocked_but_uploaded_empty_returns_zero(tmp_path):
    provider = Provider(BrainTurn(status="accepted", turn_kind="scene_query", instruction="count",
                                  scene_query=SceneQueryIntent(query_type="count", semantic_name="apple")))
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path / "out")), provider=provider)
    report = app.handle("有几个苹果")
    assert report.run_status == "blocked" and report.error.code == "scene_required"
    assert report.scene_created is False and "scene_config" not in report.artifacts
    path = tmp_path / "empty.json"
    path.write_text(SceneConfig(scene_id="empty").model_dump_json())
    before = path.read_bytes()
    report = app.handle("有几个苹果", scene_path=path)
    assert report.run_status == "success" and "0" in report.reply
    assert report.scene_source == "uploaded" and path.read_bytes() == before


def test_loaded_empty_robot_never_generates_objects(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(SceneConfig(scene_id="empty").model_dump_json())
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path / "out")), provider=Provider(robot()))
    report = app.handle("抓苹果", scene_path=path)
    assert report.run_status == "blocked" and report.scene_created is False
    assert "commands" not in report.artifacts


def test_platform_commit_survives_publication_failure(tmp_path, monkeypatch):
    provider = Provider(BrainTurn(status="accepted", turn_kind="scene_edit", instruction="add",
                                  scene_edit=SceneEditIntent(operation="add", semantic_name="apple", category="fruit")))
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=provider)
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(app.writer, "publish", fail)
    report = app.handle("增加苹果")
    assert report.error.code == "artifact_write_failed"
    assert report.scene_commit_status == "committed" and report.artifacts == {}
    assert len(app.sessions[report.session_id].scene.objects) == 2


def test_local_platform_does_not_silently_enable_fake_vision(tmp_path):
    from robot_agent_brain.errors import BrainError
    with pytest.raises(BrainError, match="Vision requires"):
        BrainApplication(BrainConfig(provider="replay", vision=True, output_dir=str(tmp_path)), provider=Provider(robot()))

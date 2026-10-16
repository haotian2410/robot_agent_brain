from pathlib import Path
import pytest

from robot_agent_brain.session.original_scene_store import OriginalSceneStore
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from test_robot_profiles_state import fixture
from test_application_artifacts import Provider, robot


def test_platform_only_never_freezes_and_snapshot_is_write_once(tmp_path):
    _, scene, _ = fixture()
    store = OriginalSceneStore(tmp_path)
    assert store.capture_once(scene, platform_object_ids={2, 3, 7}, request_id="empty", source="template") is None
    assert not (tmp_path / "original_scene.json").exists()
    manifest = store.capture_once(scene, platform_object_ids={2, 3}, request_id="first", source="generated")
    original = (tmp_path / "original_scene.json").read_bytes()
    changed = scene.model_copy(deep=True)
    changed.scene_version += 1
    changed.objects[-1].object_name_in_scene = "changed"
    assert store.capture_once(changed, platform_object_ids={2, 3}, request_id="second", source="session") == manifest
    assert (tmp_path / "original_scene.json").read_bytes() == original
    assert store.load(manifest)[0] == scene


def test_missing_manifest_or_changed_hash_never_replaced(tmp_path):
    _, scene, _ = fixture()
    store = OriginalSceneStore(tmp_path)
    manifest = store.capture_once(scene, platform_object_ids={2, 3}, request_id="first", source="generated")
    with (tmp_path / "original_scene.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="original_scene_unavailable"):
        store.load(manifest)
    with pytest.raises(ValueError, match="original_scene_unavailable"):
        store.capture_once(scene, platform_object_ids={2, 3}, request_id="second", source="session")


def test_application_freezes_success_and_verifies_on_restore(tmp_path):
    provider = Provider(robot())
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=provider)
    report = app.handle("把两个苹果放进篮子")
    assert report.run_status == "success", report
    parent = tmp_path / report.session_id
    first = (parent / "original_scene.json").read_bytes()
    manifest = app.store.load(report.session_id).original_scene_manifest
    assert len(manifest.task_object_ids) == 3
    assert len(manifest.platform_object_ids) == 2
    second = app.handle("把两个苹果放进篮子", session_id=report.session_id)
    assert second.run_status == "success", second
    assert (parent / "original_scene.json").read_bytes() == first
    with (parent / "original_scene.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="original_scene_unavailable"):
        app.store.load(report.session_id)


def test_failed_first_plan_does_not_freeze_candidate(tmp_path):
    from robot_agent_brain.models.task_understanding import TaskParseOutput
    turn = TaskParseOutput.model_validate({"entities": [{"id": "apple", "name": "apple", "category": "fruit", "count": 2, "quantity_mode": "all"}],
                                         "operations": [{"type": "grasp", "target": "apple"}]}).to_brain_turn("抓两个苹果")
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path)), provider=Provider(turn))
    report = app.handle("抓两个苹果")
    assert report.run_status != "success"
    assert not (tmp_path / report.session_id / "original_scene.json").exists()


def test_no_manifest_does_not_guess_task_objects(tmp_path):
    _, scene, _ = fixture()
    assert OriginalSceneStore(tmp_path).capture_once(scene, platform_object_ids=None, request_id="x", source="uploaded") is None

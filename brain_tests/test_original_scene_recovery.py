import json
import pytest

from robot_agent_brain.session.original_scene_store import OriginalSceneStore
from test_robot_profiles_state import fixture


def interrupted(tmp_path, monkeypatch, at="original_scene_manifest.json"):
    _, scene, _ = fixture()
    store = OriginalSceneStore(tmp_path)
    original_write = store._write_once
    def crash(path, payload):
        if path.name == at:
            raise OSError("simulated crash")
        original_write(path, payload)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_write_once", crash)
        with pytest.raises(OSError, match="simulated crash"):
            store.capture_once(scene, platform_object_ids={2, 3}, request_id="first", source="generated")
    return scene


@pytest.mark.parametrize("at", ["original_scene.json", "original_scene_manifest.json", "original_scene_commit.json"])
def test_journal_recovers_first_scene_never_current_scene(tmp_path, monkeypatch, at):
    first = interrupted(tmp_path, monkeypatch, at)
    current = first.model_copy(deep=True)
    current.scene_version += 5
    current.objects[-1].object_name_in_scene = "latest is not original"
    store = OriginalSceneStore(tmp_path)
    manifest = store.capture_once(current, platform_object_ids={2, 3}, request_id="later", source="session")
    loaded, _ = store.load(manifest)
    assert loaded == first and manifest.source_request_id == "first"
    assert (tmp_path / "original_scene_commit.json").is_file()
    raw = (tmp_path / "original_scene.json").read_bytes()
    assert store.capture_once(current, platform_object_ids={2, 3}, request_id="third", source="session") == manifest
    assert (tmp_path / "original_scene.json").read_bytes() == raw


@pytest.mark.parametrize("orphan", ["original_scene.json", "original_scene_manifest.json"])
def test_no_journal_orphan_requires_explicit_recovery(tmp_path, orphan):
    _, scene, _ = fixture()
    (tmp_path / orphan).write_text("{}")
    with pytest.raises(ValueError, match="original_scene_recovery_required"):
        OriginalSceneStore(tmp_path).capture_once(scene, platform_object_ids={2, 3}, request_id="later", source="session")
    assert (tmp_path / orphan).read_text() == "{}"


def test_corrupted_prepare_record_cannot_complete_partial_snapshot(tmp_path, monkeypatch):
    interrupted(tmp_path, monkeypatch)
    path = tmp_path / "original_scene_prepare.json"
    value = json.loads(path.read_text())
    value["scene_json"] += " "
    path.write_text(json.dumps(value))
    raw = (tmp_path / "original_scene.json").read_bytes()
    with pytest.raises(ValueError, match="original_scene_unavailable"):
        OriginalSceneStore(tmp_path).load()
    assert (tmp_path / "original_scene.json").read_bytes() == raw
    assert not (tmp_path / "original_scene_manifest.json").exists()

import json
from pathlib import Path

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn, SceneEditIntent, SceneEditPlan, SceneQueryIntent
from robot_agent_brain.models.task_understanding import TaskParseOutput
from test_application_artifacts import Provider
from test_query_scene_continuity import supported_scene
from test_scene_replace import plan


def test_original_replace_finds_deleted_object_and_publishes_provenance(tmp_path):
    scene = supported_scene()
    path = tmp_path / "input.json"
    path.write_text(scene.model_dump_json(), encoding="utf-8")
    locate = TaskParseOutput.model_validate({"entities": [{"id": "apple", "name": "apple", "category": "fruit"}],
        "operations": [{"type": "locate", "target": "apple"}]}).to_brain_turn("定位苹果")
    provider = Provider(locate)
    app = BrainApplication(BrainConfig(provider="replay", output_dir=str(tmp_path / "out"), scene_platform_object_ids={0}), provider=provider)
    first = app.handle("定位苹果", scene_path=path)
    assert first.run_status == "success", first
    root = tmp_path / "out" / first.session_id
    original_bytes = (root / "original_scene.json").read_bytes()
    provider.turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="删除苹果",
                             scene_edit=plan([{"operation": "remove", "target": "old"}]))
    removed = app.handle("删除苹果", session_id=first.session_id)
    assert removed.run_status == "success", removed
    provider.turn = BrainTurn(status="accepted", turn_kind="scene_edit", instruction="在原始场景把苹果替换成香蕉",
                             scene_edit=plan().model_copy(update={"scene_basis": "original"}))
    replaced = app.handle("在原始场景把苹果替换成香蕉", session_id=first.session_id)
    assert replaced.run_status == "success", replaced
    assert replaced.scene_id != first.scene_id and replaced.scene_version == 1
    assert "commands" not in replaced.artifacts and "scene_patch" not in replaced.artifacts
    assert (root / "original_scene.json").read_bytes() == original_bytes
    record = json.loads((root / replaced.request_id / "request_record.json").read_text(encoding="utf-8"))
    assert record["scene_basis"] == "original" and record["source_snapshot"]
    assert record["id_remap"]
    new_scene = json.loads(Path(replaced.artifacts["scene_config"]).read_text(encoding="utf-8"))
    assert all(o["object_id_in_scene"] not in {0, 1, 2} for o in new_scene["objects"])
    # Repeat from the same immutable original, not the previous banana result.
    again = app.handle("在原始场景把苹果替换成香蕉", session_id=first.session_id)
    assert again.run_status == "success", again
    assert again.scene_id != replaced.scene_id
    assert provider.count == 4


def test_empty_import_is_frozen_before_first_edit_and_reused_for_original_adds(tmp_path):
    source_scene = supported_scene().model_copy(update={"objects": [supported_scene().objects[0]]})
    path = tmp_path / "empty_platform.json"
    path.write_text(source_scene.model_dump_json(), encoding="utf-8")
    provider = Provider(BrainTurn(
        status="accepted", turn_kind="scene_query", instruction="有几个香蕉",
        scene_query=SceneQueryIntent(query_type="count", target="banana",
                                     entities=[{"entity_id": "banana", "semantic_name": "banana", "category": "fruit"}]),
    ))
    app = BrainApplication(
        BrainConfig(provider="replay", output_dir=str(tmp_path / "out"), scene_platform_object_ids={0}),
        provider=provider,
    )
    first = app.handle("有几个香蕉", scene_path=path)
    assert first.run_status == "success", first
    root = tmp_path / "out" / first.session_id
    manifest = json.loads((root / "original_scene_manifest.json").read_text(encoding="utf-8"))
    original = json.loads((root / "original_scene.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "uploaded"
    assert manifest["task_object_ids"] == []
    assert len(original["objects"]) == 1

    original_add = BrainTurn(
        status="accepted", turn_kind="scene_edit", instruction="在原始场景把桌子改成蓝色",
        scene_edit=SceneEditPlan(
            scene_basis="original",
            entities=[{"entity_id": "table", "semantic_name": "table", "category": "surface"}],
            operations=[SceneEditIntent(operation="update_properties", target="table", properties={"color": "blue"})],
        ),
    )
    provider.turn = original_add
    derived = app.handle("在原始场景把桌子改成蓝色", session_id=first.session_id)
    repeated = app.handle("再次在原始场景把桌子改成蓝色", session_id=first.session_id)
    assert derived.run_status == repeated.run_status == "success"
    assert derived.scene_id != repeated.scene_id
    assert derived.scene_version == repeated.scene_version == 1
    assert (root / "original_scene.json").read_bytes() == json.dumps(original, ensure_ascii=False, sort_keys=True, indent=2).encode()

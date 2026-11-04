import json
import shutil
import tempfile
from pathlib import Path

import httpx

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.models.qwen_http import QwenHTTPProvider
from robot_agent_brain.models.task_understanding import TaskUnderstandingRequest


ROOT = Path(__file__).resolve().parents[1]


def _provider_response():
    value = {
        "protocol_version": "task_understanding.v3.1",
        "status": "accepted", "turn_kind": "session_control",
        "clarification_question": None,
        "scene_edit": None, "scene_query": None, "session_control": {"action": "pause"},
        "robot_setup_request": None, "entities": [], "operations": [], "relations": [],
    }
    return {"choices": [{"message": {"content": json.dumps(value)}, "finish_reason": "stop"}]}


def test_catalog_snapshot_namespaces_models_and_robots_without_merging_ids():
    catalog = json.loads((ROOT / "config/final_models.json").read_text())
    root = catalog["asset_library_root"]
    if not Path(root).is_absolute():
        root = str((ROOT / "config" / root).resolve())
    cache = catalog.get("asset_geometry_cache")
    if cache and not Path(cache).is_absolute():
        cache = str((ROOT / "config" / cache).resolve())
    categories = str((ROOT / "config" / catalog["asset_category_index"]).resolve())
    adapter = FinalModelsLibraryAdapter(root, geometry_cache=cache, category_index=categories,
                                        library_ref_prefix=catalog["library_ref_prefix"])
    snapshot = adapter.catalog_snapshot(aliases={"杯子": "mug", "马克杯": "mug"})
    assert "model:1" in snapshot.model_keys()
    assert any(item.asset_key == "robot:1" for item in snapshot.robots)
    mug = next(item for item in snapshot.models if item.name == "mug")
    assert "杯子" in mug.aliases
    assert snapshot.revision.startswith("sha256:")


def test_understanding_request_sends_catalog_workspace_and_scene_context():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=_provider_response())

    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
                                transport=httpx.MockTransport(handler))
    provider.understand_turn(TaskUnderstandingRequest(instruction="pause"))
    body = json.loads(requests[0]["messages"][1]["content"])
    assert body["protocol_version"] == "task_understanding.v3.1"
    assert body["workspace"]["mode"] == "tabletop"
    assert "asset_catalog" not in body or "models" in body["asset_catalog"]


def test_live_qwen_payload_contains_full_current_ols_catalog_and_scenes():
    config = json.loads((ROOT / "config/webeditor.json").read_text())
    root = Path(config["asset_library_root"])
    if not root.is_absolute():
        root = (ROOT / "config" / root).resolve()
    cache = Path(config["asset_geometry_cache"])
    if not cache.is_absolute():
        cache = (ROOT / "config" / cache).resolve()
    categories = (ROOT / "config" / config["asset_category_index"]).resolve()
    adapter = FinalModelsLibraryAdapter(root, geometry_cache=cache, category_index=categories,
                                        library_ref_prefix=config["library_ref_prefix"])
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=_provider_response())

    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
                                transport=httpx.MockTransport(handler))
    snapshot = adapter.catalog_snapshot(aliases={"杯子": "mug", "马克杯": "mug", "cup": "mug"})
    provider.understand_turn(TaskUnderstandingRequest(
        instruction="暂停", asset_catalog=snapshot,
        scene_context={"basis": "bootstrap", "primary_table_available": True}))
    body = json.loads(requests[0]["messages"][1]["content"])
    model_index = json.loads((root / "models" / "model_index.json").read_text())
    robot_index = json.loads((root / "robots" / "robot_index.json").read_text())
    scene_index = json.loads((root / "scenes" / "scene_index.json").read_text())
    assert len(body["asset_catalog"]["models"]) == len(model_index["by_id"])
    assert len(body["asset_catalog"]["robots"]) == len(robot_index["by_id"])
    assert len(body["asset_catalog"]["scenes"]) == len(scene_index)
    assert {item["name"] for item in body["asset_catalog"]["scenes"]} >= {"ur5e_table_empty", "piper_table_twist"}
    assert "scene_name=ur5e_table_empty" in requests[0]["messages"][0]["content"]


def test_per_turn_catalog_keeps_registered_profiles_in_payload_and_revision():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset

    first = AssetCatalogSnapshot.from_items(
        [CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True)], [],
        registered_profiles=["ur5e"])
    second = AssetCatalogSnapshot.from_items(
        [CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True)], [],
        registered_profiles=["piper"])
    assert first.revision != second.revision
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=_provider_response())

    provider = QwenHTTPProvider("http://example/v1", "qwen-test",
                                transport=httpx.MockTransport(handler), asset_catalog=first)
    provider.understand_turn(TaskUnderstandingRequest(instruction="暂停", asset_catalog=second))
    body = json.loads(requests[0]["messages"][1]["content"])
    assert body["asset_catalog"]["revision"] == second.revision
    assert body["asset_catalog"]["registered_profiles"] == ["piper"]


def test_future_cup_name_is_not_attached_as_mug_alias():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset

    snapshot = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="mug", aliases=("杯子",), selectable_for_add=True),
        CatalogAsset(asset_key="model:2", name="cup", selectable_for_add=True),
    ], [])
    mug = next(item for item in snapshot.models if item.name == "mug")
    cup = next(item for item in snapshot.models if item.name == "cup")
    assert mug.asset_key != cup.asset_key and "cup" not in mug.aliases


def test_ols_adapter_refresh_publishes_new_catalog_atomically():
    """A changed read-only OLS index is visible on the next snapshot."""
    config = json.loads((ROOT / "config/webeditor.json").read_text())
    source = Path(config["asset_library_root"])
    if not source.is_absolute():
        source = (ROOT / "config" / source).resolve()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        # Metadata/index JSON is sufficient for catalog refresh; meshes are
        # intentionally not copied, keeping this test independent of OBJ/PNG.
        for section, index_name in (("models", "model_index.json"),
                                    ("robots", "robot_index.json"),
                                    ("scenes", "scene_index.json")):
            (target / section).mkdir()
            shutil.copy2(source / section / index_name, target / section / index_name)
            index = json.loads((source / section / index_name).read_text())
            entries = index["by_id"] if section != "scenes" else {str(item["id"]): item["name"] for item in index}
            for identifier, name in entries.items():
                source_meta = source / section / str(identifier) / f"{name}.json"
                if source_meta.is_file():
                    destination = target / section / str(identifier)
                    destination.mkdir()
                    shutil.copy2(source_meta, destination / source_meta.name)
        adapter = FinalModelsLibraryAdapter(target)
        before = adapter.catalog_snapshot().revision
        index_path = target / "models" / "model_index.json"
        index = json.loads(index_path.read_text())
        index["by_id"]["999"] = "test_cube"
        index["by_name"]["test_cube"] = [999]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        metadata = json.loads((target / "models/1/apple.json").read_text())
        metadata["semantic_properties"].update(object_id=999, object_name="test_cube")
        destination = target / "models/999"
        destination.mkdir()
        (destination / "test_cube.json").write_text(json.dumps(metadata), encoding="utf-8")
        assert adapter.refresh_from_source() is True
        assert adapter.catalog_snapshot().revision != before
        assert any(item.name == "test_cube" for item in adapter.catalog_snapshot().models)


def test_catalog_snapshot_keeps_scene_templates_separate_from_addable_models():
    catalog = json.loads((ROOT / "config/webeditor.json").read_text())
    root = Path(catalog["asset_library_root"])
    if not root.is_absolute():
        root = (ROOT / "config" / root).resolve()
    cache = Path(catalog["asset_geometry_cache"])
    if not cache.is_absolute():
        cache = (ROOT / "config" / cache).resolve()
    categories = (ROOT / "config" / catalog["asset_category_index"]).resolve()
    adapter = FinalModelsLibraryAdapter(root, geometry_cache=cache, category_index=categories,
                                        library_ref_prefix=catalog["library_ref_prefix"])
    snapshot = adapter.catalog_snapshot()
    assert len(snapshot.scenes) == 7
    assert any(item.scene_key == "scene:1" and item.name == "ur5e_table_empty" for item in snapshot.scenes)
    assert all(not item.scene_key.startswith("model:") for item in snapshot.scenes)


def test_live_table_side_words_canonicalize_to_tabletop_regions():
    from robot_agent_brain.models.task_understanding import parse_qwen_turn

    value = {
        "protocol_version": "task_understanding.v3.1", "status": "accepted",
        "turn_kind": "scene_edit", "clarification_question": None,
        "scene_edit": {
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "asset_choices": [{"entity_id": "apple", "asset_key": "model:1"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "apple", "relation": "on", "reference": "table"}],
        },
        "scene_query": None, "session_control": None, "robot_setup_request": None,
        "entities": [], "operations": [], "relations": [],
    }
    turn = parse_qwen_turn(value, "在桌子左侧增加一个苹果")
    assert turn.scene_edit.operations[0].placement_region == "left_half"
    assert turn.status.value == "accepted"


def test_live_asset_choice_rejects_non_selectable_or_name_mismatch():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
    from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError

    catalog = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="apple", selectable_for_add=True),
        CatalogAsset(asset_key="model:2", name="microwave", selectable_for_add=False),
    ], [])
    request = TaskUnderstandingRequest(instruction="增加苹果", asset_catalog=catalog)
    value = {"protocol_version": "task_understanding.v3.1", "status": "accepted",
             "turn_kind": "scene_edit", "scene_edit": {
                 "entities": [{"entity_id": "apple", "semantic_name": "banana", "category": "fruit"}],
                 "operations": [{"operation": "add", "target": "apple"}],
                 "asset_choices": [{"entity_id": "apple", "asset_key": "model:1"}],
             }}
    try:
        QwenHTTPProvider._validate_live_asset_choices(value, request)
    except QwenProviderError as exc:
        assert exc.code == "asset_catalog_key_invalid"
        assert "asset_choice_name_mismatch" in str(exc)
    else:
        raise AssertionError("a catalog key must agree with its canonical semantic name")

    value["scene_edit"]["entities"][0]["semantic_name"] = "microwave"
    value["scene_edit"]["asset_choices"][0]["asset_key"] = "model:2"
    try:
        QwenHTTPProvider._validate_live_asset_choices(value, request)
    except QwenProviderError as exc:
        assert exc.code == "asset_catalog_key_invalid"
        assert "asset_not_selectable_for_scene_edit" in str(exc)
    else:
        raise AssertionError("passive models cannot be selected for a scene add")

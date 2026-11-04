import json
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


def test_future_cup_name_is_not_attached_as_mug_alias():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset

    snapshot = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="mug", aliases=("杯子",), selectable_for_add=True),
        CatalogAsset(asset_key="model:2", name="cup", selectable_for_add=True),
    ], [])
    mug = next(item for item in snapshot.models if item.name == "mug")
    cup = next(item for item in snapshot.models if item.name == "cup")
    assert mug.asset_key != cup.asset_key and "cup" not in mug.aliases


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

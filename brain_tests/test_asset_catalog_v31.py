import json
import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.contracts.scene import SceneComponent, SceneConfig, SceneObject
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


def test_asset_prompt_labels_passive_platform_and_tabletop_usage():
    """The full catalog must expose capability boundaries, not only names."""
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
    from robot_agent_brain.models.prompts import build_asset_catalog_prompt
    prompt, _ = build_asset_catalog_prompt(adapter)
    assert "model:29" in prompt and "usage=support_surface" in prompt
    assert "model:25" in prompt and "usage=passive_mechanism_capability_boundary" in prompt
    assert "model:30" in prompt and "availability=passive_mechanism_only" in prompt
    assert "robot:1" in prompt and "usage=robot_platform_capability_boundary" in prompt


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


def test_pipeline_refreshes_live_ols_before_each_understanding_turn():
    from robot_agent_brain.contracts.turn import BrainTurn, SessionControlIntent, TurnKind, TurnStatus
    from robot_agent_brain.pipeline import BrainPipeline

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
    refreshes = []
    adapter.refresh_from_source = lambda: refreshes.append(True) or False

    class Provider:
        def __init__(self):
            self.requests = []

        def understand_turn(self, request):
            self.requests.append(request)
            return BrainTurn(status=TurnStatus.ACCEPTED, turn_kind=TurnKind.SESSION_CONTROL,
                             instruction=request.instruction,
                             session_control=SessionControlIntent(action="pause"))

    provider = Provider()
    pipeline = BrainPipeline(provider, adapter)
    pipeline.understand_turn("暂停")
    pipeline.understand_turn("继续")
    assert len(refreshes) == 2
    assert all(request.asset_catalog is not None for request in provider.requests)
    assert all(request.asset_catalog.revision == pipeline.asset_catalog.revision
               for request in provider.requests)


def test_live_pipeline_http_sends_full_catalog_on_every_turn():
    """Verify the real pipeline/provider boundary, not only a fake provider."""
    from robot_agent_brain.pipeline import BrainPipeline

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
    pipeline = BrainPipeline(provider, adapter)
    pipeline.understand_turn("暂停")
    pipeline.understand_turn("继续")
    model_index = json.loads((root / "models" / "model_index.json").read_text())
    robot_index = json.loads((root / "robots" / "robot_index.json").read_text())
    scene_index = json.loads((root / "scenes" / "scene_index.json").read_text())
    assert len(requests) == 2
    for body in requests:
        catalog = body["messages"][1]["content"]
        payload = json.loads(catalog)
        assert len(payload["asset_catalog"]["models"]) == len(model_index["by_id"])
        assert len(payload["asset_catalog"]["robots"]) == len(robot_index["by_id"])
        assert len(payload["asset_catalog"]["scenes"]) == len(scene_index)
        assert payload["asset_catalog"]["revision"].startswith("sha256:")
        assert "model:1" in body["messages"][0]["content"]


def test_future_cup_name_is_not_attached_as_mug_alias():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset

    snapshot = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="mug", aliases=("杯子",), selectable_for_add=True),
        CatalogAsset(asset_key="model:2", name="cup", selectable_for_add=True),
    ], [])
    mug = next(item for item in snapshot.models if item.name == "mug")
    cup = next(item for item in snapshot.models if item.name == "cup")
    assert mug.asset_key != cup.asset_key and "cup" not in mug.aliases


def test_live_pipeline_catalog_uses_revision_scoped_alias_data():
    """Mug-only catalogs expose aliases, but never shadow a real cup asset."""
    from robot_agent_brain.pipeline import BrainPipeline

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
    adapter.catalog_aliases = {"cup": "mug", "杯子": "mug", "马克杯": "mug"}
    pipeline = BrainPipeline(object(), adapter, aliases={"cup": "mug", "杯子": "mug"})
    mug = next(item for item in pipeline.asset_catalog.models if item.name == "mug")
    assert "cup" in mug.aliases
    assert "杯子" in mug.aliases
    # Deterministic grounding still retains the compatibility alias table.
    assert pipeline.aliases["cup"] == "mug"

    # Live callers omit ``aliases`` deliberately: the adapter's
    # revision-scoped vocabulary is injected into the Qwen prompt.  In this
    # mug-only catalog all language forms are useful evidence for selection.
    provider = QwenHTTPProvider("http://example/v1", "qwen-test")
    provider.set_asset_catalog(adapter, aliases=None)
    prompt_mug = next(item for item in provider.asset_catalog_snapshot.models if item.name == "mug")
    assert {"cup", "杯子", "马克杯"}.issubset(set(prompt_mug.aliases))

    # Simulate a later OLS publication that adds a canonical cup entry.  The
    # canonical token is reserved and must no longer be attached to mug.
    mug_view = next(view for key, view in adapter._assets.items()
                    if key == "model:" + str(mug.asset_key.split(":", 1)[1]))
    cup_view = mug_view.model_copy(update={
        "library_asset_id": 999999,
        "metadata_ref": "$LIBRARY_SERVER/999999",
        "semantic_name": "cup",
    })
    adapter._assets["model:999999"] = cup_view
    evolved = adapter.catalog_snapshot()
    evolved_mug = next(item for item in evolved.models if item.name == "mug")
    evolved_cup = next(item for item in evolved.models if item.name == "cup")
    assert "cup" not in evolved_mug.aliases
    assert evolved_cup.asset_key != evolved_mug.asset_key


def test_understanding_context_distinguishes_bootstrap_from_uploaded_empty_scene():
    """The tabletop bootstrap is implicit only before a SceneConfig exists."""
    from robot_agent_brain.pipeline import BrainPipeline
    from robot_agent_brain.contracts.scene import SceneConfig

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
    pipeline = BrainPipeline(object(), adapter)

    bootstrap = pipeline._understanding_scene_context(None)
    uploaded_empty = pipeline._understanding_scene_context(
        SceneConfig(scene_schema_version=1, scene_id=123, scene_name="uploaded-empty", objects=[]))
    assert bootstrap["basis"] == "bootstrap"
    assert bootstrap["primary_table_available"] is True
    assert uploaded_empty["basis"] == "current"
    assert uploaded_empty["primary_table_available"] is False
    assert uploaded_empty["objects"] == []


def test_scene_context_only_advertises_configured_primary_table_identity():
    """A tabletop surface is not a primary support unless its OLS ref is bound."""
    from robot_agent_brain.pipeline import BrainPipeline

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
    pipeline = BrainPipeline(object(), adapter,
                             primary_table_metadata_ref=config["default_table_metadata_ref"])

    def table(identifier, ref, kind="model"):
        return SceneObject(object_id_in_scene=identifier, object_name_in_scene="table",
            components=[
                SceneComponent(component_type="Transform", properties={
                    "position": [0, 0, 0], "quaternion_xyzw": [0, 0, 0, 1],
                    "scale": [1, 1, 1], "parent": None}),
                SceneComponent(component_type="Semantic", properties={
                    "semantic_name": "table", "category": "surface", "support": None}),
                SceneComponent(component_type="MetadataRef", properties={"path": ref, "type": kind}),
            ])

    wrong_ref = SceneConfig(scene_schema_version=1, scene_id=1, scene_name="wrong",
                            objects=[table(10, "$LIBRARY_SERVER/30")])
    assert pipeline._understanding_scene_context(wrong_ref)["primary_table_available"] is False

    right_ref = SceneConfig(scene_schema_version=1, scene_id=2, scene_name="right",
                            objects=[table(10, "$LIBRARY_SERVER/29")])
    context = pipeline._understanding_scene_context(right_ref)
    assert context["primary_table_available"] is True
    assert context["primary_table_object_id"] == 10

    missing_type = SceneConfig(scene_schema_version=1, scene_id=3, scene_name="missing-type",
                               objects=[table(10, "$LIBRARY_SERVER/29", kind=None)])
    assert pipeline._understanding_scene_context(missing_type)["primary_table_available"] is False


def test_ols_adapter_refresh_publishes_new_catalog_atomically():
    """A refresh publishes complete state or leaves the old catalog intact."""
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
        before_keys = adapter.catalog_snapshot().model_keys()
        apple_metadata_path = target / "models/1/apple.json"
        apple_metadata = json.loads(apple_metadata_path.read_text(encoding="utf-8"))
        apple_metadata["semantic_properties"]["object_name"] = "not_apple"
        apple_metadata_path.write_text(json.dumps(apple_metadata), encoding="utf-8")
        with pytest.raises(ValueError, match=r"asset_metadata_name_mismatch: model/1"):
            adapter.refresh_from_source()
        # A failed constructor must not expose a cleared or half-reloaded
        # catalog to the next turn.
        assert adapter.catalog_snapshot().revision == before
        assert adapter.catalog_snapshot().model_keys() == before_keys
        apple_metadata["semantic_properties"]["object_name"] = "apple"
        apple_metadata_path.write_text(json.dumps(apple_metadata), encoding="utf-8")
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


def test_live_table_region_normalization_does_not_rewrite_object_relative_add():
    from robot_agent_brain.models.task_understanding import parse_qwen_turn

    value = {
        "protocol_version": "task_understanding.v3.1", "status": "accepted",
        "turn_kind": "scene_edit", "clarification_question": None,
        "scene_edit": {
            "scene_basis": "current",
            "entities": [
                {"entity_id": "apple", "semantic_name": "apple", "category": "fruit"},
                {"entity_id": "banana", "semantic_name": "banana", "category": "fruit"},
            ],
            "asset_choices": [{"entity_id": "banana", "asset_key": "model:2"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "banana",
                             "relation": "left_of", "reference": "apple"}],
        },
        "scene_query": None, "session_control": None, "robot_setup_request": None,
        "entities": [], "operations": [], "relations": [],
    }
    turn = parse_qwen_turn(value, "在苹果左侧增加一个香蕉")
    operation = turn.scene_edit.operations[0]
    assert operation.relation.value == "left_of"
    assert operation.reference == "apple"
    assert operation.placement_region is None


def test_live_table_relative_region_is_canonicalized_to_on_region():
    from robot_agent_brain.models.task_understanding import parse_qwen_turn

    value = {
        "protocol_version": "task_understanding.v3.1", "status": "accepted",
        "turn_kind": "scene_edit", "clarification_question": None,
        "scene_edit": {
            "scene_basis": "current",
            "entities": [{"entity_id": "apple", "semantic_name": "apple", "category": "fruit"}],
            "asset_choices": [{"entity_id": "apple", "asset_key": "model:1"}],
            "relations": [],
            "operations": [{"operation": "add", "target": "apple",
                             "relation": "left_of", "reference": "table"}],
        },
        "scene_query": None, "session_control": None, "robot_setup_request": None,
        "entities": [], "operations": [], "relations": [],
    }
    turn = parse_qwen_turn(value, "在桌子左侧增加一个苹果")
    operation = turn.scene_edit.operations[0]
    assert operation.relation.value == "on"
    assert operation.reference == "table"
    assert operation.placement_region == "left_half"


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


def test_live_catalog_request_rejects_legacy_v3_before_name_fallback():
    from robot_agent_brain.contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
    from robot_agent_brain.models.qwen_http import QwenHTTPProvider, QwenProviderError

    catalog = AssetCatalogSnapshot.from_items([
        CatalogAsset(asset_key="model:1", name="mug", selectable_for_add=True),
    ], [])
    value = {"protocol_version": "task_understanding.v3", "status": "accepted",
             "turn_kind": "scene_edit", "scene_edit": {
                 "entities": [{"entity_id": "cup", "semantic_name": "cup", "category": "container"}],
                 "operations": [{"operation": "add", "target": "cup"}],
                 "asset_choices": [{"entity_id": "cup", "asset_key": "model:1"}],
             }}
    request = TaskUnderstandingRequest(instruction="增加一个杯子", asset_catalog=catalog)
    try:
        QwenHTTPProvider._validate_live_asset_choices(value, request)
    except QwenProviderError as exc:
        assert exc.code == "provider_output_schema_invalid"
        assert "v3.1" in str(exc)
    else:
        raise AssertionError("live catalog requests must not fall back to the legacy v3 name resolver")

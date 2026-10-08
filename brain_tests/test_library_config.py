import json

import pytest

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.application import BrainApplication
from robot_agent_brain.adapters.local_asset_library import LocalAssetLibraryAdapter
from robot_agent_brain.contracts.turn import BrainTurn, SceneQueryIntent
from robot_agent_brain.contracts.task_intent import TaskEntity
from test_asset_library import library, script
from test_component_runtime import scene_


def configuration(tmp_path):
    root, cache = library(tmp_path)
    assert script("build_asset_geometry_cache.py", "--asset-root", root, "--output", cache).returncode == 0
    aliases = tmp_path / "aliases.json"
    aliases.write_text(json.dumps({"苹果": "apple"}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider": "replay", "asset_library_root": "assets",
        "asset_geometry_cache": "cache.json", "semantic_aliases": "aliases.json",
        "output_dir": str(tmp_path / "output")}))
    return BrainConfig.load(config, environ={})


def test_real_adapter_config_relative_paths_and_aliases(tmp_path):
    config = configuration(tmp_path)
    assets = config.load_assets()
    assert isinstance(assets, LocalAssetLibraryAdapter)
    assert assets.resolve("$LIBRARY_SERVER/1").semantic_name == "apple"
    assert config.load_semantic_aliases() == {"苹果": "apple"}
    assert config.default_table_metadata_ref is None
    assert config.default_robot_metadata_ref is None


@pytest.mark.parametrize("fields", [
    {"asset_library_root": "assets"},
    {"asset_geometry_cache": "cache.json"},
    {"asset_category_index": "categories.json"},
    {"assets": "demo.json", "asset_library_root": "assets", "asset_geometry_cache": "cache.json"},
])
def test_library_misconfiguration_not_silent_demo_fallback(fields):
    with pytest.raises(ValueError, match="asset_library_config"):
        BrainConfig(**fields)


def test_application_query_with_real_library_and_restore(tmp_path):
    config = configuration(tmp_path)
    class QueryProvider:
        def understand_turn(self, request):
            return BrainTurn(status="accepted", turn_kind="scene_query", instruction=request.instruction,
                scene_query=SceneQueryIntent(query_type="count", target="a",
                    entities=[TaskEntity(entity_id="a", semantic_name="苹果", category="fruit")]))
    app = BrainApplication(config, provider=QueryProvider())
    assert app.config_summary["demo_assets"] is False
    session = app.get_session("s")
    session.initialize_scene(scene_())
    result = session.run_task("r", "几个苹果")
    assert result.scene_query_result.count == 2
    app.store.save("s", session, revision=1, config_fingerprint=app.config_fingerprint)
    restored = BrainApplication(config, provider=QueryProvider()).get_session("s")
    assert restored.run_task("r2", "几个苹果").scene_query_result.count == 2
    assert restored.seen_scene_object_ids == {0, 8, 11, 12}

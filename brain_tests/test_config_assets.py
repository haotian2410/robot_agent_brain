import json
import pytest
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.model_property import ModelProperty
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.asset_resolver import AssetResolver


def entity(name="苹果", **kwargs):
    return TaskEntity(entity_id="a", semantic_name=name, category="fruit", **kwargs)


def test_demo_resources_alias_and_missing_color_evidence():
    config = BrainConfig.load(environ={})
    assert config.model is None
    assert config.load_defaults().initial_counts == {}
    catalog = config.load_assets()
    resolver = AssetResolver(catalog, aliases=catalog.metadata.aliases)
    result = resolver.resolve(entity())
    assert result.model.semantic_name == "apple"
    assert result.assumptions and catalog.metadata.demo_assets
    with pytest.raises(ValueError, match="asset_color_evidence_missing"):
        resolver.resolve(entity(color="red"))


def test_config_precedence_and_secrets(tmp_path):
    file = tmp_path / "settings.json"
    file.write_text(json.dumps({"model": "file", "timeout": 9, "assets": "assets.json"}))
    config = BrainConfig.load(file, environ={"ROBOT_BRAIN_MODEL": "env", "ROBOT_BRAIN_API_KEY": "private"},
                              overrides={"model": "cli"})
    assert config.model == "cli" and config.timeout == 9
    assert config.assets == str(tmp_path / "assets.json")
    assert "private" not in config.model_dump_json()
    assert "private" not in repr(config)
    assert BrainConfig.load(file, environ={"ROBOT_BRAIN_MODEL": "env"}).model == "env"
    file.write_text('{"api_key":"forbidden"}')
    with pytest.raises(ValueError, match="config_secret_forbidden"):
        BrainConfig.load(file, environ={})


def test_explicit_missing_catalog_never_falls_back(tmp_path):
    with pytest.raises(FileNotFoundError):
        BrainConfig(assets=str(tmp_path / "missing.json")).load_assets()


def test_missing_and_category_ambiguity():
    resolver = AssetResolver(BrainConfig().load_assets())
    with pytest.raises(ValueError, match="asset_missing"):
        resolver.resolve(entity("pear"))
    with pytest.raises(ValueError, match="asset_ambiguous"):
        resolver.resolve(entity("fruit", category_only=True))


def test_duplicate_ids_alias_conflicts_and_copy_isolation():
    model = ModelProperty(asset_id="a", semantic_name="apple", category="fruit", dimensions_m=(1, 1, 1))
    with pytest.raises(ValueError, match="asset_id_duplicate"):
        LocalAssetCatalog([model, model])
    catalog = LocalAssetCatalog([model])
    catalog.get_model_property("a").semantic_name = "banana"
    assert catalog.get_model_property("a").semantic_name == "apple"
    with pytest.raises(ValueError, match="asset_alias_invalid"):
        LocalAssetCatalog.from_document({"models": [model.model_dump()], "aliases": {"apple": "pear"}})
    with pytest.raises(ValueError, match="asset_color_evidence_missing"):
        AssetResolver(catalog).resolve(entity("apple", color="red"))


@pytest.mark.parametrize("dimensions,aabb", [((float("nan"), 1, 1), None),
    ((float("inf"), 1, 1), None), ((0, 1, 1), None), ((1, 1, 1), (1, 0, 0, 0, 1, 1))])
def test_invalid_model_geometry(dimensions, aabb):
    with pytest.raises(ValueError):
        ModelProperty(asset_id="a", semantic_name="apple", category="fruit", dimensions_m=dimensions, aabb_m=aabb)

"""Compatibility checks for the latest local ObjectLibraryServer checkout."""
from pathlib import Path
import os

import pytest

from robot_agent_brain.adapters.final_models_library import FinalModelsLibraryAdapter
from robot_agent_brain.adapters.ols_robot_assembly import OlsRobotAssemblyAdapter
from robot_agent_brain.config import BrainConfig


OLS_ROOT = Path(os.environ["ROBOT_BRAIN_OLS_DATA_ROOT"]) if os.environ.get("ROBOT_BRAIN_OLS_DATA_ROOT") else None


@pytest.fixture
def latest_config():
    path = Path(__file__).parents[1] / "config" / "webeditor_ols_latest.json"
    if OLS_ROOT is None or not OLS_ROOT.is_dir():
        pytest.skip("latest local OLS checkout is not installed")
    return BrainConfig.load(path, overrides={"vision": False, "provider": "replay"})


def test_latest_ols_catalog_and_scene_names(latest_config):
    assets = latest_config.load_assets()
    assert len(assets.find_by_name("apple")) == 1
    assert assets.resolve("$LIBRARY_SERVER/1", asset_type="robot").semantic_name == "ur5"
    assert {scene.name for scene in assets._scenes} >= {
        "ur5_table_empty", "ur5_table_sorting", "piper_table_twist"
    }


def test_ur5e_legacy_alias_resolves_latest_ur5(latest_config):
    assembly = OlsRobotAssemblyAdapter(latest_config.load_assets())
    assert assembly.resolve("ur5e_arm", role="arm").semantic_name == "ur5"
    assert assembly.resolve("ur5e", role="arm").semantic_name == "ur5"
    assert assembly.resolve("ur5", role="arm").semantic_name == "ur5"


def test_latest_config_points_at_current_ols_scene(latest_config):
    assert Path(latest_config.default_scene).is_file()
    assert Path(latest_config.default_scene).name == "ur5_table_empty.json"
    assert latest_config.editor_scene_manifests["ur5_table_empty"] == [0, 1, 2, 3, 4, 5, 6, 7]

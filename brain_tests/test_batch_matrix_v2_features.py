import json
from pathlib import Path

from robot_agent_brain.batch import load_batch_input
from robot_agent_brain.batch_matrix import compile_matrix
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.prompts import build_asset_catalog_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_v2_workbooks_compile_and_carry_metadata():
    catalog = ROOT / "config" / "batch_asset_catalog.json"
    root = Path("/home/cscvlab/lht/webeditor_runtime/ObjectLibraryServer-1.0.7-dev-a6bc69a/data")
    for name, kind in (("generated_edit_matrix_v2.xlsx", "generated_edit"), ("known_scene_matrix_v2.xlsx", "known_scene")):
        document, manifest = compile_matrix(ROOT / "examples" / "matrices" / name, kind=kind,
                                            asset_roles=ROOT / "config" / "batch_asset_roles.json", seed=20261103,
                                            asset_root=root, asset_catalog=catalog, schema_version=2)
        assert document["sessions"]
        assert manifest["schema_version"] == 2
        assert all("expected_outcome" in item for item in document["sessions"])


def test_asset_prompt_contains_ols_names_and_aliases():
    config = BrainConfig.load(ROOT / "config" / "webeditor.json")
    prompt, digest = build_asset_catalog_prompt(config.load_assets())
    assert digest and "apple" in prompt and "banana" in prompt and "mug" in prompt
    assert "杯子" in prompt and "semantic_name" in prompt
    assert str(ROOT) not in prompt


def test_v2_json_loads_with_backward_compatible_batch_model():
    loaded = load_batch_input(ROOT / "examples" / "batch_sessions_generated_v2.json")
    assert loaded["kind"] == "sessions"
    assert loaded["sessions"][0].test_id
    assert loaded["sessions"][0].expected_outcome

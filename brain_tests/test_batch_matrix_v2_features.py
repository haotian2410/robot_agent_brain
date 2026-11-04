import json
from pathlib import Path

from robot_agent_brain.batch import load_batch_input
from robot_agent_brain.batch_matrix import BatchMatrixError
from robot_agent_brain.batch_matrix_v2 import compile_semantic_matrix_v2, read_semantic_matrix_v2
from robot_agent_brain.batch_matrix_v2 import _asset_for_role
from robot_agent_brain.cli import main as cli_main
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.models.prompts import build_asset_catalog_prompt


ROOT = Path(__file__).resolve().parents[1]


def test_v2_uses_authoritative_workbook_and_expands_all_variants():
    workbook = ROOT / "docs" / "semantic-refactor" / "02_semantic_test_matrix.xlsx"
    catalog = ROOT / "config" / "batch_asset_catalog.json"
    roles = ROOT / "docs" / "semantic-refactor" / "07_asset_roles_template.json"
    spec = read_semantic_matrix_v2(workbook, strict_counts=True)
    document, manifest = compile_semantic_matrix_v2(
        workbook, kind="generated_edit", asset_roles=roles,
        seed=20261103, asset_catalog=catalog, strict_counts=True)
    assert spec["counts"] == {"cases": 20, "variants": 115}
    assert manifest["schema"] == "brain-semantic-matrix.v2"
    assert manifest["case_count"] == 20
    assert manifest["invariant_count"] == 27
    assert manifest["session_count"] == 115
    assert len(document["sessions"]) == 115
    assert all("expected_outcome" in item for item in document["sessions"])


def test_legacy_two_sheet_examples_are_not_accepted_as_v2():
    # These files are retained as historical/manual examples.  They do not
    # contain the authoritative variants and invariant sheets, so a v2 call
    # must fail explicitly instead of silently falling back to compile_matrix.
    for name in ("generated_edit_matrix_v2.xlsx", "known_scene_matrix_v2.xlsx"):
        try:
            read_semantic_matrix_v2(ROOT / "examples" / "matrices" / name, strict_counts=True)
        except BatchMatrixError as exc:
            assert str(exc) == "semantic_matrix_v2_sheet_missing:matrix,variants"
        else:  # pragma: no cover - guards against accidental legacy fallback
            raise AssertionError(f"legacy workbook unexpectedly accepted as v2: {name}")


def test_v2_role_kind_is_checked_against_catalog_category():
    catalog = {
        "model:1": {"asset_key": "model:1", "semantic_name": "apple", "category": "fruit"},
        "model:29": {"asset_key": "model:29", "semantic_name": "table", "category": "surface"},
    }
    assert _asset_for_role("object_a", catalog,
                           {"object_a": {"kind": "pickable", "candidates": ["apple"]}},
                           seed=1, case_id="T01", sample=1)["semantic_name"] == "apple"
    try:
        _asset_for_role("object_a", catalog,
                        {"object_a": {"kind": "pickable", "candidates": ["table"]}},
                        seed=1, case_id="T01", sample=1)
    except BatchMatrixError as exc:
        assert str(exc) == "semantic_matrix_v2_role_candidates_missing:object_a:table"
    else:  # pragma: no cover
        raise AssertionError("surface asset was accepted for pickable role")
    surface = _asset_for_role(
        "surface_1",
        {"model:29": {"asset_key": "model:29", "semantic_name": "table",
                       "category": "surface", "passive_or_platform": True}},
        {"surface_1": {"kind": "surface", "candidates": ["table"]}},
        seed=1, case_id="T02", sample=1)
    assert surface["semantic_name"] == "table"
    try:
        _asset_for_role("placement_1", catalog,
                        {"placement_1": {"kind": "container", "candidates": ["apple"]}},
                        seed=1, case_id="T02", sample=1)
    except BatchMatrixError as exc:
        assert str(exc) == "semantic_matrix_v2_role_candidates_missing:placement_1:apple"
    else:  # pragma: no cover
        raise AssertionError("fruit asset was accepted for container role")


def test_schema_version_two_never_falls_back_to_legacy_compiler(tmp_path):
    output = tmp_path / "compiled.json"
    rc = cli_main([
        "batch-compile", "--matrix", str(ROOT / "docs" / "semantic-refactor" / "02_semantic_test_matrix.xlsx"),
        "--kind", "generated_edit", "--asset-roles", str(ROOT / "docs" / "semantic-refactor" / "07_asset_roles_template.json"),
        "--asset-catalog", str(ROOT / "config" / "batch_asset_catalog.json"),
        "--schema-version", "2", "--seed", "20261103", "--output", str(output),
    ])
    assert rc == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema_version"] == 2
    assert document["matrix_version"] == 2
    assert len(document["sessions"]) == 115


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

import json
from pathlib import Path

from robot_agent_brain.batch_matrix_v2 import compile_semantic_matrix_v2, read_semantic_matrix_v2


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "docs/semantic-refactor/02_semantic_test_matrix.xlsx"
ROLES = ROOT / "docs/semantic-refactor/07_asset_roles_template.json"
CATALOG = ROOT / "config/batch_asset_catalog.json"


def test_authoritative_workbook_has_expected_shape():
    spec = read_semantic_matrix_v2(WORKBOOK, strict_counts=True)
    assert spec["counts"] == {"cases": 20, "variants": 115}
    assert [row["case_id"] for row in spec["cases"][:5]] == ["T01", "T02", "T03", "T04", "T05"]
    assert all(isinstance(row["expected_json_value"], dict) for row in spec["variants"])


def test_v2_compilation_expands_all_variants_and_is_seed_stable(tmp_path):
    first, manifest = compile_semantic_matrix_v2(WORKBOOK, asset_roles=ROLES,
                                                  asset_catalog=CATALOG, seed=20261103,
                                                  strict_counts=True,
                                                  output=tmp_path / "one.json")
    second, _ = compile_semantic_matrix_v2(WORKBOOK, asset_roles=ROLES,
                                           asset_catalog=CATALOG, seed=20261103,
                                           strict_counts=True)
    assert len(first["sessions"]) == 115
    assert first == second
    assert manifest["variant_count"] == 115
    assert {item["variant_id"] for item in first["sessions"]} >= {"T01.V01", "T05.V10", "T20.V04"}
    assert all(item["asset_role_mapping"] for item in first["sessions"] if item["test_id"] not in {"T19", "T20"})


def test_v2_compilation_does_not_use_legacy_length_slice(tmp_path):
    _, manifest = compile_semantic_matrix_v2(WORKBOOK, asset_roles=ROLES,
                                              asset_catalog=CATALOG, seed=20261103,
                                              strict_counts=True, output=tmp_path / "compiled.json")
    assert manifest["session_count"] == 115
    output = json.loads((tmp_path / "compiled.json").read_text())
    assert len(output["sessions"]) == 115


def test_v2_catalog_scenarios_survive_compilation_for_isolated_contract_cases():
    """T19's isolated OLS scenarios must not be discarded as metadata."""
    document, manifest = compile_semantic_matrix_v2(
        WORKBOOK, asset_roles=ROLES, asset_catalog=CATALOG, seed=20261103,
        strict_counts=True)
    t19 = [item for item in document["sessions"] if item.get("test_id") == "T19"]
    assert {item.get("catalog_scenario") for item in t19} == {
        "mug_only", "mug_and_cup", "mug_removed_cup_present",
        "mug_only_no_handle_compatible_asset",
    }
    manifest_t19 = [item for item in manifest["rows"] if item.get("case_id") == "T19"]
    assert all("catalog_scenario" in item for item in manifest_t19)

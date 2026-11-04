import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from robot_agent_brain.batch_matrix_v2 import (BatchMatrixError, _validate_expected_contract,
                                               compile_semantic_matrix_v2, read_semantic_matrix_v2)


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "docs/semantic-refactor/02_semantic_test_matrix.xlsx"
ROLES = ROOT / "docs/semantic-refactor/07_asset_roles_template.json"
CATALOG = ROOT / "config/batch_asset_catalog.json"


def test_authoritative_workbook_has_expected_shape():
    spec = read_semantic_matrix_v2(WORKBOOK, strict_counts=True)
    assert spec["counts"] == {"cases": 20, "variants": 115}
    assert [row["case_id"] for row in spec["cases"][:5]] == ["T01", "T02", "T03", "T04", "T05"]
    assert all(isinstance(row["expected_json_value"], dict) for row in spec["variants"])


def test_exported_plan_matches_checked_in_json_schema():
    plan = json.loads((ROOT / "docs/semantic-refactor/03_semantic_test_plan.json").read_text())
    schema = json.loads((ROOT / "docs/semantic-refactor/04_test_plan.schema.json").read_text())
    Draft202012Validator(schema).validate(plan)


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


def test_expected_json_route_contract_rejects_shallow_oracle_typos():
    row = {"_row": 17}
    with pytest.raises(BatchMatrixError, match="scene_edit_requires_operation"):
        _validate_expected_contract({"route": "scene_edit"}, "scene_updated", row)
    with pytest.raises(BatchMatrixError, match="scene_query_requires_query_type"):
        _validate_expected_contract({"route": "scene_query", "query_type": "count"}, "answered", row)
    with pytest.raises(BatchMatrixError, match="route_missing"):
        _validate_expected_contract({"scene_unchanged": True}, "safe_rejection", row)


def test_expected_json_route_contract_keeps_clarification_and_catalog_cases_open():
    _validate_expected_contract({"actionable_payload_absent": True, "required_missing_slot": "reference"},
                                "clarification_required", {"_row": 18})
    _validate_expected_contract({"allowed_catalog_names": ["mug"], "selected_asset_key_in_request": True},
                                "semantic_accepted", {"_row": 19})


def test_expected_json_deep_schema_accepts_route_operation_shapes():
    row = {"_row": 22}
    _validate_expected_contract({
        "route": "scene_edit", "operation": "add", "target_role": "object_a",
        "relation": "on", "reference_role": "surface_1", "region": "right_front",
        "placement_hint": "any", "count": 1,
    }, "scene_updated", row)
    _validate_expected_contract({
        "route": "scene_edit", "operation": "scale", "target_role": "object_a",
        "scale_mode": "multiply", "scale_xyz": [1.1, 1.1, 1.1],
    }, "scene_updated", row)
    _validate_expected_contract({
        "route": "scene_query", "query_type": "selection", "target_role": "object_a",
        "selection": "nearest", "reference_role": "placement_1", "selected_count": 1,
    }, "answered", row)
    _validate_expected_contract({
        "route": "robot_task", "operation": "place", "executed": False,
    }, "plan_ready", row)


@pytest.mark.parametrize(
    ("payload", "outcome", "message"),
    [
        ({"route": "scene_edit", "operation": "add", "target_role": "object_a",
          "relation": "near"}, "scene_updated", "relation_reference_must_be_paired"),
        ({"route": "scene_edit", "operation": "rotate", "target_role": "object_a",
          "axis": "z", "angle_deg": "ninety"}, "scene_updated", "angle_deg_type"),
        ({"route": "scene_edit", "operation": "scale", "target_role": "object_a",
          "scale_mode": "multiply", "scale_xyz": [1.0, 0.0, 1.0]}, "scene_updated", "scale_xyz_type"),
        ({"route": "scene_edit", "operations": ["what:object_a"]}, "scene_updated", "operation_invalid"),
        ({"route": "scene_query", "query_type": "selection", "target_role": "object_a",
          "selection": "nearest"}, "answered", "selection_requires_reference_role"),
        ({"route": "robot_task", "operation": "place", "executed": True}, "plan_ready", "plan_ready_requires_executed=false"),
    ],
)
def test_expected_json_deep_schema_rejects_malformed_nested_contract(payload, outcome, message):
    with pytest.raises(BatchMatrixError, match=message):
        _validate_expected_contract(payload, outcome, {"_row": 23})

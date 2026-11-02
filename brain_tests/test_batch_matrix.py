import json

import pytest

openpyxl = pytest.importorskip("openpyxl")

from robot_agent_brain.batch_matrix import BatchMatrixError, compile_matrix, read_matrix


GENERATED = [
    "enabled", "flow_id", "parent_flow_id", "difficulty", "stage", "round_index",
    "category", "sample_count", "role_a", "role_b", "placement_1", "placement_2",
    "instruction_template", "variants", "branch_policy", "notes",
]
KNOWN = [
    "enabled", "scene_name", "difficulty", "category", "sample_count",
    "instruction_template", "variants", "role_a", "role_b", "round_index", "notes",
]


def _book(path, headers, rows):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "matrix"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(path)


def _roles(path):
    path.write_text(json.dumps({
        "object_a": {"kind": "pickable", "candidates": ["apple", "banana"]},
        "surface_1": {"kind": "surface", "candidates": ["table"]},
    }), encoding="utf-8")


def test_generated_matrix_expands_variants_and_records_seed(tmp_path):
    matrix = tmp_path / "matrix.xlsx"
    _book(matrix, GENERATED, [[1, "flow", "", "L1", "generate", 1, "add", 2,
                               "object_a", "", "", "", "在{surface_1}上增加一个{object_a}",
                               "{object_a}", "seed_parent", ""]])
    roles = tmp_path / "roles.json"
    _roles(roles)
    document, manifest = compile_matrix(matrix, kind="generated_edit", asset_roles=roles,
                                        seed=123, asset_root=None)
    assert len(document["sessions"]) == 2
    assert all("在桌子上增加一个" in s["instructions"][0] for s in document["sessions"])
    assert manifest["seed"] == 123
    assert manifest["session_count"] == 2


def test_matrix_missing_column_has_precise_error(tmp_path):
    matrix = tmp_path / "bad.xlsx"
    _book(matrix, ["enabled", "flow_id"], [[1, "flow"]])
    with pytest.raises(BatchMatrixError, match="batch_matrix_columns_missing"):
        read_matrix(matrix, "generated_edit")


def test_known_scene_requires_existing_scene_and_writes_relative_path(tmp_path):
    matrix = tmp_path / "known.xlsx"
    _book(matrix, KNOWN, [[1, "missing_scene", "L1", "query", 1, "有{object_a}吗", "{object_a}", "object_a", "", 1, ""]])
    roles = tmp_path / "roles.json"
    _roles(roles)
    with pytest.raises(BatchMatrixError, match="unknown scene"):
        compile_matrix(matrix, kind="known_scene", asset_roles=roles, seed=1,
                       asset_root=tmp_path / "assets")


def test_invalid_round_and_placeholder_are_rejected(tmp_path):
    matrix = tmp_path / "bad.xlsx"
    _book(matrix, GENERATED, [[1, "flow", "", "L1", "generate", 11, "add", 1,
                               "object_a", "", "", "", "{unknown}", "苹果", "seed_parent", ""]])
    with pytest.raises(BatchMatrixError, match="round_index"):
        read_matrix(matrix, "generated_edit")

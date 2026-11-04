"""Importer/compiler for the ``brain-semantic-matrix.v2`` workbook.

This module is intentionally separate from the historical v1 matrix reader.
The v2 workbook has one feature per row and one complete expression per row in
the ``variants`` sheet.  It never interprets a bare variant as a value and it
never truncates a row to ``sample_count``.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .batch_matrix import (BatchMatrixError, _cell, _enabled, _fields, _render,
                           load_asset_catalog_document)


MATRIX_COLUMNS = (
    "enabled", "case_id", "name", "parent_case_id", "parent_variant_policy",
    "parent_variant_id", "fixture_id", "role_a", "role_b", "asset_samples",
    "repeats_per_variant", "variant_selection", "execution_layer", "priority",
    "variant_count", "variant_preview", "notes", "status",
)
VARIANT_COLUMNS = (
    "enabled", "case_id", "variant_id", "variant_kind", "equivalence_group",
    "instruction_template", "expected_outcome", "expected_json", "precondition",
    "catalog_scenario", "notes", "status",
)
INVARIANT_COLUMNS = ("test_id", "priority", "module", "name", "input", "assertion")
ALLOWED_POLICIES = {"none", "fixed", "seed", "all"}
ALLOWED_OUTCOMES = {"scene_updated", "answered", "clarification_required", "safe_rejection",
                    "plan_ready", "capability_unsupported", "blocked", "semantic_accepted", "robot_setup_updated"}
ALLOWED_EXPECTED_ROUTES = {"scene_edit", "scene_query", "robot_task", "robot_config"}
V2_PLACEHOLDERS = {"object_a", "object_b", "placement_1", "placement_2", "surface_1"}
SCENE_EDIT_OPERATIONS = {"add", "remove", "replace", "translate", "move_relative", "rotate",
                         "scale", "update_properties"}
SCENE_EDIT_RELATIONS = {"left_of", "right_of", "front_of", "behind", "above", "below", "near", "on", "inside"}
SCENE_EDIT_REGIONS = {"any", "center", "left_half", "right_half", "front_half", "back_half",
                      "left_front", "right_front", "left_back", "right_back"}
SCENE_QUERY_TYPES = {"count", "existence", "selection", "relation", "neighbors", "position"}
SCENE_QUERY_SELECTIONS = {"nearest", "farthest", "leftmost", "rightmost", "frontmost", "backmost"}
TRANSLATE_DIRECTIONS = {"left", "right", "front", "back", "above", "below", "up", "down"}
SCALE_DIRECTIONS = {"enlarge", "shrink"}
SCALE_AMOUNTS = {"small", "medium", "large"}


def _contract_error(row: dict[str, Any], detail: str) -> None:
    raise BatchMatrixError(
        f"semantic_matrix_v2_expected_contract_invalid:variants!expected_json{row['_row']}:{detail}")


def _contract_field(expected: dict[str, Any], name: str, row: dict[str, Any], *, required: bool = False,
                    types: tuple[type, ...] = (str,), allow_none: bool = False) -> Any:
    """Read and type-check one expected-json field.

    This intentionally reports a JSON path-like field name.  Workbook authors
    otherwise get a late assertion failure with no indication which part of a
    nested route contract was malformed.
    """
    value = expected.get(name)
    if value is None:
        if required and not allow_none:
            _contract_error(row, f"{name}_missing")
        return value
    if allow_none and value is None:
        return value
    if not isinstance(value, types) or (str in types and isinstance(value, str) and not value.strip()):
        labels = "/".join(item.__name__ for item in types)
        _contract_error(row, f"{name}_type={labels}")
    return value


def _contract_bool(expected: dict[str, Any], name: str, row: dict[str, Any], *, required: bool = False) -> Any:
    return _contract_field(expected, name, row, required=required, types=(bool,))


def _contract_number(expected: dict[str, Any], name: str, row: dict[str, Any], *, required: bool = False,
                     allow_none: bool = False) -> Any:
    value = _contract_field(expected, name, row, required=required, types=(int, float), allow_none=allow_none)
    if value is not None and (isinstance(value, bool) or not math.isfinite(float(value))):
        _contract_error(row, f"{name}_finite")
    return value


def _contract_string_list(expected: dict[str, Any], name: str, row: dict[str, Any], *, required: bool = False) -> Any:
    value = expected.get(name)
    if value is None:
        if required:
            _contract_error(row, f"{name}_missing")
        return value
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        _contract_error(row, f"{name}_type=list[str]")
    return value


def _validate_operation_token(value: Any, row: dict[str, Any], index: int) -> None:
    """Validate the compact operation form used by the authoritative sheet.

    Existing matrix rows use values such as ``add:object_a`` and
    ``translate:object_a:right:0.05``.  New matrices may use object entries;
    both forms are checked instead of allowing an arbitrary list of strings.
    """
    path = f"operations[{index}]"
    if isinstance(value, str):
        parts = value.split(":")
        if not parts or parts[0] not in (SCENE_EDIT_OPERATIONS | {"color"}):
            _contract_error(row, f"{path}.operation_invalid")
        if len(parts) < 2 or not parts[1].strip():
            _contract_error(row, f"{path}.target_role_missing")
        if parts[0] == "translate" and len(parts) >= 4:
            try:
                distance = float(parts[3])
            except ValueError:
                _contract_error(row, f"{path}.distance_m_type")
            if not math.isfinite(distance):
                _contract_error(row, f"{path}.distance_m_finite")
        return
    if not isinstance(value, dict):
        _contract_error(row, f"{path}.type=list|string|object")
    operation = value.get("operation", value.get("type"))
    if not isinstance(operation, str) or operation not in SCENE_EDIT_OPERATIONS:
        _contract_error(row, f"{path}.operation_invalid")
    for name in ("target_role", "reference_role", "replacement_role"):
        if name in value and value[name] is not None and (not isinstance(value[name], str) or not value[name].strip()):
            _contract_error(row, f"{path}.{name}_type=string")
    if "count" in value and (not isinstance(value["count"], int) or isinstance(value["count"], bool) or value["count"] < 1):
        _contract_error(row, f"{path}.count_type=positive_integer")


def _validate_expected_contract(expected: dict[str, Any], outcome: str, row: dict[str, Any]) -> None:
    """Validate the small, machine-readable oracle contract in each variant.

    ``expected_json`` is intentionally not a provider payload: it describes
    the assertion an oracle must make.  Still, accepting an arbitrary object
    makes a typo in a workbook indistinguishable from a real test.  Validate
    the route-specific discriminator and the minimum fields needed by the
    corresponding oracle while leaving feature-specific assertion keys open.
    """
    route = expected.get("route")
    if route is None:
        if outcome == "clarification_required":
            if expected.get("actionable_payload_absent") is not True:
                _contract_error(row, "clarification_requires_actionable_payload_absent=true")
            if "required_missing_slot" in expected and (not isinstance(expected["required_missing_slot"], str) or
                                                        not expected["required_missing_slot"].strip()):
                _contract_error(row, "required_missing_slot_type=string")
            if "must_not_drop" in expected and (not isinstance(expected["must_not_drop"], str) or
                                                 not expected["must_not_drop"].strip()):
                _contract_error(row, "must_not_drop_type=string")
            return
        if outcome == "semantic_accepted":
            _contract_string_list(expected, "allowed_catalog_names", row, required=True)
            flags = ["selected_asset_key_in_request", "exact_catalog_name_respected", "no_stale_key"]
            if not any(expected.get(flag) is True for flag in flags):
                _contract_error(row, "catalog_acceptance_requires_selection_evidence")
            for flag in flags:
                if flag in expected and not isinstance(expected[flag], bool):
                    _contract_error(row, f"{flag}_type=boolean")
            return
        _contract_error(row, "route_missing")
    if not isinstance(route, str) or not route.strip():
        _contract_error(row, "route_type=string")
    if route not in ALLOWED_EXPECTED_ROUTES:
        _contract_error(row, f"route={route}")
    # These fields are shared by several routes.  Validate them before the
    # route discriminator so a malformed scalar cannot silently pass merely
    # because its route has a permissive extension field.
    if "count" in expected and (not isinstance(expected["count"], int) or isinstance(expected["count"], bool) or expected["count"] < 1):
        _contract_error(row, "count_type=positive_integer")
    if "count_delta" in expected and (not isinstance(expected["count_delta"], int) or isinstance(expected["count_delta"], bool)):
        _contract_error(row, "count_delta_type=integer")
    for name in ("allowed_error_codes", "error_codes", "allowed_catalog_names"):
        if name in expected:
            _contract_string_list(expected, name, row)
    for name in ("atomic", "scene_unchanged", "preserve_instance", "preserve_pose", "preserve_orientation",
                 "platform_unchanged", "new_instance_required", "non_targets_unchanged", "original_hash_unchanged",
                 "same_instance", "table_and_task_objects_unchanged"):
        if name in expected and not isinstance(expected[name], bool):
            _contract_error(row, f"{name}_type=boolean")
    if route == "scene_edit":
        operation = expected.get("operation")
        operations = expected.get("operations")
        if operation is None and not (isinstance(operations, list) and operations):
            _contract_error(row, "scene_edit_requires_operation_or_operations")
        if operation is not None:
            if not isinstance(operation, str) or operation not in SCENE_EDIT_OPERATIONS:
                _contract_error(row, "operation_invalid")
            target_required = outcome not in {"safe_rejection", "clarification_required"}
            _contract_field(expected, "target_role", row, required=target_required)
            if operation in {"add", "move_relative"}:
                relation = expected.get("relation")
                reference = expected.get("reference_role")
                if relation is not None and relation not in SCENE_EDIT_RELATIONS:
                    _contract_error(row, f"relation_invalid={relation}")
                if (relation is None) != (reference is None):
                    _contract_error(row, "relation_reference_must_be_paired")
                if reference is not None and (not isinstance(reference, str) or not reference.strip()):
                    _contract_error(row, "reference_role_type=string")
            if operation == "add":
                region = expected.get("region")
                placement_hint = expected.get("placement_hint")
                if region is not None and region not in SCENE_EDIT_REGIONS:
                    _contract_error(row, f"region_invalid={region}")
                if placement_hint is not None and placement_hint not in {"any", "center"}:
                    _contract_error(row, f"placement_hint_invalid={placement_hint}")
            elif operation == "rotate":
                if outcome not in {"safe_rejection", "clarification_required"}:
                    axis = _contract_field(expected, "axis", row, required=True)
                    if axis not in {"x", "y", "z", "local_x", "local_y", "local_z"}:
                        _contract_error(row, f"axis_invalid={axis}")
                    _contract_number(expected, "angle_deg", row, required=True)
            elif operation == "translate":
                if outcome not in {"safe_rejection", "clarification_required"}:
                    direction = _contract_field(expected, "direction", row, required=True)
                    if direction not in TRANSLATE_DIRECTIONS:
                        _contract_error(row, f"direction_invalid={direction}")
                    distance = _contract_number(expected, "distance_m", row, allow_none=True)
                    motion_scale = expected.get("motion_scale")
                    if motion_scale is not None and (not isinstance(motion_scale, str) or not motion_scale.strip()):
                        _contract_error(row, "motion_scale_type=string|null")
                    if distance is None and motion_scale is None:
                        _contract_error(row, "translate_requires_distance_or_motion_scale")
            elif operation == "scale":
                if outcome not in {"safe_rejection", "clarification_required"}:
                    scale_xyz = expected.get("scale_xyz")
                    has_xyz = isinstance(scale_xyz, list)
                    has_direction = expected.get("scale_direction") is not None or expected.get("scale_amount") is not None
                    if has_xyz == has_direction:
                        _contract_error(row, "scale_requires_exactly_one_mode")
                    if has_xyz:
                        if len(scale_xyz) != 3 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                                                     not math.isfinite(float(value)) or float(value) <= 0 for value in scale_xyz):
                            _contract_error(row, "scale_xyz_type=positive_number[3]")
                    else:
                        if expected.get("scale_direction") not in SCALE_DIRECTIONS or expected.get("scale_amount") not in SCALE_AMOUNTS:
                            _contract_error(row, "scale_direction_or_amount_invalid")
            elif operation == "update_properties" and outcome not in {"safe_rejection", "clarification_required"}:
                color = _contract_field(expected, "color", row, required=True)
                if not isinstance(color, str) or not color.strip():
                    _contract_error(row, "color_type=string")
            elif operation == "replace" and outcome not in {"safe_rejection", "clarification_required"}:
                _contract_field(expected, "replacement_role", row, required=True)
            elif operation == "remove" and outcome not in {"safe_rejection", "clarification_required"}:
                count = expected.get("count")
                all_available = expected.get("all_available")
                if count is None and all_available is not True:
                    _contract_error(row, "remove_requires_count_or_all_available")
                if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 1):
                    _contract_error(row, "count_type=positive_integer")
        if operations is not None:
            if not isinstance(operations, list) or not operations:
                _contract_error(row, "operations_type=non_empty_list")
            for index, item in enumerate(operations):
                _validate_operation_token(item, row, index)
    elif route == "scene_query":
        if not isinstance(expected.get("query_type"), str) or not expected.get("query_type", "").strip() or (
                outcome not in {"safe_rejection", "clarification_required"} and
                (not isinstance(expected.get("target_role"), str) or not expected.get("target_role", "").strip())):
            # Keep the historical discriminator in the error text while also
            # naming the concrete missing field for workbook diagnostics.
            missing = "query_type" if not isinstance(expected.get("query_type"), str) or not expected.get("query_type", "").strip() else "target_role"
            _contract_error(row, f"scene_query_requires_query_type_and_target_role:{missing}_missing")
        query_type = _contract_field(expected, "query_type", row, required=True)
        target_required = outcome not in {"safe_rejection", "clarification_required"}
        _contract_field(expected, "target_role", row, required=target_required)
        if query_type not in SCENE_QUERY_TYPES:
            _contract_error(row, f"query_type_invalid={query_type}")
        if "reference_role" in expected and expected["reference_role"] is not None and not isinstance(expected["reference_role"], str):
            _contract_error(row, "reference_role_type=string|null")
        if query_type == "selection":
            selection = _contract_field(expected, "selection", row, required=outcome not in {"safe_rejection", "clarification_required"})
            if selection is not None and selection not in SCENE_QUERY_SELECTIONS:
                _contract_error(row, f"selection_invalid={selection}")
            if selection in {"nearest", "farthest"} and not expected.get("reference_role") and outcome not in {"safe_rejection", "clarification_required"}:
                _contract_error(row, "selection_requires_reference_role")
        elif query_type == "relation" and outcome not in {"safe_rejection", "clarification_required"}:
            _contract_field(expected, "reference_role", row, required=True)
            predicate = expected.get("predicate", expected.get("relation"))
            if not isinstance(predicate, str) or not predicate.strip():
                _contract_error(row, "relation_query_requires_predicate")
        elif query_type == "neighbors" and "reference_role" in expected and expected.get("reference_role") is not None:
            _contract_error(row, "neighbors_query_reference_role_forbidden")
        if "selected_count" in expected and (not isinstance(expected["selected_count"], int) or isinstance(expected["selected_count"], bool) or expected["selected_count"] < 1):
            _contract_error(row, "selected_count_type=positive_integer")
    elif route == "robot_task":
        operation = expected.get("operation")
        operations = expected.get("operations")
        if operation is None and not (isinstance(operations, list) and operations):
            _contract_error(row, "robot_task_requires_operation_or_operations")
        if operation is not None and (not isinstance(operation, str) or not operation.strip()):
            _contract_error(row, "operation_type=string")
        if operations is not None and (not isinstance(operations, list) or not operations):
            _contract_error(row, "operations_type=non_empty_list")
        if "executed" in expected and not isinstance(expected["executed"], bool):
            _contract_error(row, "executed_type=boolean")
        if outcome == "plan_ready" and expected.get("executed") is not False:
            _contract_error(row, "plan_ready_requires_executed=false")
    elif route == "robot_config":
        mode = _contract_field(expected, "mode", row, required=True)
        profile_registered = _contract_bool(expected, "profile_registered", row, required=True)
        if mode not in {"single", "dual"} or profile_registered is not True:
            _contract_error(row, "robot_config_requires_registered_profile")
        if "executed" in expected and not isinstance(expected["executed"], bool):
            _contract_error(row, "executed_type=boolean")


def _openpyxl():
    try:
        import openpyxl  # type: ignore
    except ModuleNotFoundError as exc:
        raise BatchMatrixError("batch_matrix_requires_openpyxl") from exc
    return openpyxl


def _headers(ws, sheet: str) -> dict[str, int]:
    row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    if row is None:
        raise BatchMatrixError(f"semantic_matrix_v2_sheet_empty:{sheet}")
    values = [_cell(value) for value in row]
    return {name: index for index, name in enumerate(values)}


def _required(headers: dict[str, int], columns: tuple[str, ...], sheet: str):
    missing = [name for name in columns if name not in headers]
    if missing:
        raise BatchMatrixError(f"semantic_matrix_v2_columns_missing:{sheet}:{','.join(missing)}")


def _read_rows(ws, sheet: str, required: tuple[str, ...], *, enabled_column: bool = True) -> list[dict[str, Any]]:
    positions = _headers(ws, sheet)
    _required(positions, required, sheet)
    rows = []
    for row_number, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        item = {name: values[index] if index < len(values) else None for name, index in positions.items()}
        item["_row"] = row_number
        if enabled_column and not _enabled(item.get("enabled")):
            continue
        rows.append(item)
    return rows


def read_semantic_matrix_v2(path: str | Path, *, strict_counts: bool = False) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.is_file():
        raise BatchMatrixError(f"semantic_matrix_v2_not_found:{source}")
    book = _openpyxl().load_workbook(source, read_only=True, data_only=True)
    if "matrix" not in book.sheetnames or "variants" not in book.sheetnames:
        raise BatchMatrixError("semantic_matrix_v2_sheet_missing:matrix,variants")
    if strict_counts:
        required_sheets = {"说明", "基线与角色", "方向契约", "回归断言",
                           "运行配置", "结果模板", "源码依据"}
        missing_sheets = sorted(required_sheets - set(book.sheetnames))
        if missing_sheets:
            raise BatchMatrixError("semantic_matrix_v2_sheet_missing:" + ",".join(missing_sheets))
    matrix = _read_rows(book["matrix"], "matrix", MATRIX_COLUMNS)
    variants = _read_rows(book["variants"], "variants", VARIANT_COLUMNS)
    if "回归断言" not in book.sheetnames:
        raise BatchMatrixError("semantic_matrix_v2_sheet_missing:回归断言")
    # The supplied workbook keeps the invariant sheet reader-facing Chinese
    # headers.  Normalize them here; matrix/variants intentionally use stable
    # English contract names.
    invariant_sheet = book["回归断言"]
    invariant_headers = _headers(invariant_sheet, "回归断言")
    invariant_aliases = {
        "模块": "module", "测试名称": "name", "构造输入": "input",
        "必须满足的断言": "assertion",
    }
    invariant_rows = _read_rows(invariant_sheet, "回归断言",
                                 ("test_id", "priority", "模块", "测试名称", "构造输入", "必须满足的断言"),
                                 enabled_column=False)
    invariants = []
    for item in invariant_rows:
        normalized = dict(item)
        for source_name, target_name in invariant_aliases.items():
            normalized[target_name] = normalized.pop(source_name)
        invariants.append(normalized)
    cases = {str(row["case_id"]).strip(): row for row in matrix}
    if len(cases) != len(matrix):
        raise BatchMatrixError("semantic_matrix_v2_duplicate_case_id")
    if strict_counts and len(matrix) != 20:
        raise BatchMatrixError(f"semantic_matrix_v2_case_count:{len(matrix)}:expected=20")
    if strict_counts and len(variants) != 115:
        raise BatchMatrixError(f"semantic_matrix_v2_variant_count:{len(variants)}:expected=115")
    if strict_counts and len(invariants) != 27:
        raise BatchMatrixError(f"semantic_matrix_v2_invariant_count:{len(invariants)}:expected=27")
    expected_first = ["T01", "T02", "T03", "T04", "T05"]
    if [str(row["case_id"]).strip() for row in matrix[:5]] != expected_first:
        raise BatchMatrixError("semantic_matrix_v2_first_five_must_be_T01_T05")
    variant_by_id: dict[str, dict[str, Any]] = {}
    variants_by_case: dict[str, list[dict[str, Any]]] = {}
    for variant_index, item in enumerate(variants):
        case_id, variant_id = str(item.get("case_id") or "").strip(), str(item.get("variant_id") or "").strip()
        if case_id not in cases:
            raise BatchMatrixError(f"semantic_matrix_v2_unknown_variant_case:variants!case_id{item['_row']}:{case_id}")
        if not variant_id or variant_id in variant_by_id:
            raise BatchMatrixError(f"semantic_matrix_v2_duplicate_variant_id:variants!variant_id{item['_row']}:{variant_id}")
        template = _cell(item.get("instruction_template"))
        unknown = _fields(template) - V2_PLACEHOLDERS
        if unknown:
            raise BatchMatrixError(f"semantic_matrix_v2_unknown_placeholder:variants!instruction_template{item['_row']}:{','.join(sorted(unknown))}")
        if not template:
            raise BatchMatrixError(f"semantic_matrix_v2_empty_instruction:variants!instruction_template{item['_row']}")
        expected_outcome = _cell(item.get("expected_outcome"))
        if expected_outcome not in ALLOWED_OUTCOMES:
            raise BatchMatrixError(f"semantic_matrix_v2_outcome_invalid:variants!expected_outcome{item['_row']}:{expected_outcome}")
        raw_expected = item.get("expected_json")
        try:
            expected = json.loads(raw_expected) if isinstance(raw_expected, str) else raw_expected
        except json.JSONDecodeError as exc:
            raise BatchMatrixError(f"semantic_matrix_v2_expected_json_invalid:variants!expected_json{item['_row']}") from exc
        if not isinstance(expected, dict):
            raise BatchMatrixError(f"semantic_matrix_v2_expected_json_object:variants!expected_json{item['_row']}")
        _validate_expected_contract(expected, expected_outcome, item)
        item = {**item, "case_id": case_id, "variant_id": variant_id,
                "instruction_template": template, "expected_json_value": expected,
                "expected_outcome": expected_outcome}
        variants[variant_index] = item
        variant_by_id[variant_id] = item
        variants_by_case.setdefault(case_id, []).append(item)
    for row in matrix:
        case_id = str(row["case_id"]).strip()
        if case_id not in variants_by_case:
            raise BatchMatrixError(f"semantic_matrix_v2_case_has_no_variants:matrix!case_id{row['_row']}:{case_id}")
        parent = _cell(row.get("parent_case_id")) or "NONE"
        policy = (_cell(row.get("parent_variant_policy")) or "none").casefold()
        if policy not in ALLOWED_POLICIES:
            raise BatchMatrixError(f"semantic_matrix_v2_parent_policy_invalid:matrix!parent_variant_policy{row['_row']}:{policy}")
        if parent != "NONE" and parent not in cases:
            raise BatchMatrixError(f"semantic_matrix_v2_parent_missing:matrix!parent_case_id{row['_row']}:{parent}")
        if parent == case_id:
            raise BatchMatrixError(f"semantic_matrix_v2_parent_self:matrix!parent_case_id{row['_row']}")
        if parent == "NONE" and policy != "none":
            raise BatchMatrixError(f"semantic_matrix_v2_parent_policy_without_parent:matrix!parent_variant_policy{row['_row']}:{policy}")
        if parent != "NONE" and policy == "none":
            raise BatchMatrixError(f"semantic_matrix_v2_parent_policy_missing:matrix!parent_variant_policy{row['_row']}")
        row["case_id"] = case_id
        row["parent_case_id"] = None if parent == "NONE" else parent
        row["parent_variant_policy"] = policy
        if policy == "fixed":
            parent_variant = _cell(row.get("parent_variant_id"))
            if parent is None or parent_variant not in variant_by_id or variant_by_id[parent_variant]["case_id"] != parent:
                raise BatchMatrixError(f"semantic_matrix_v2_parent_variant_invalid:matrix!parent_variant_id{row['_row']}:{parent_variant}")
        elif _cell(row.get("parent_variant_id")):
            raise BatchMatrixError(f"semantic_matrix_v2_parent_variant_forbidden:matrix!parent_variant_id{row['_row']}")
        try:
            row["asset_samples"] = int(row.get("asset_samples") or 1)
            row["repeats_per_variant"] = int(row.get("repeats_per_variant") or 1)
        except (TypeError, ValueError) as exc:
            raise BatchMatrixError(f"semantic_matrix_v2_integer_invalid:matrix!asset_samples{row['_row']}") from exc
        if row["asset_samples"] < 1 or row["repeats_per_variant"] < 1:
            raise BatchMatrixError(f"semantic_matrix_v2_positive_counts:matrix!asset_samples{row['_row']}")
        if _cell(row.get("variant_selection")) not in {"all", "enabled"}:
            raise BatchMatrixError(f"semantic_matrix_v2_variant_selection_invalid:matrix!variant_selection{row['_row']}")
    invariant_ids = [str(item.get("test_id") or "").strip() for item in invariants]
    if any(not value for value in invariant_ids) or len(invariant_ids) != len(set(invariant_ids)):
        raise BatchMatrixError("semantic_matrix_v2_duplicate_or_empty_invariant_id")
    # Detect cycles in the case DAG.
    visiting, visited = set(), set()
    def visit(case_id: str):
        if case_id in visiting:
            raise BatchMatrixError(f"semantic_matrix_v2_parent_cycle:{case_id}")
        if case_id in visited:
            return
        visiting.add(case_id)
        parent = cases[case_id].get("parent_case_id")
        if parent:
            visit(parent)
        visiting.remove(case_id); visited.add(case_id)
    for case_id in cases:
        visit(case_id)
    return {"path": str(source), "cases": matrix, "variants": variants,
            "invariants": invariants, "invariant_count": len(invariants),
            "cases_by_id": cases, "variants_by_id": variant_by_id,
            "variants_by_case": variants_by_case, "counts": {"cases": len(matrix), "variants": len(variants)}}


def _stable_index(seed: int, *parts: str, size: int) -> int:
    digest = hashlib.sha256((str(seed) + "|" + "|".join(parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _derived_seed(seed: int, *parts: str) -> int:
    """Derive a reproducible axis seed without consuming global PRNG state.

    Matrix v2 deliberately keeps the three axes (asset choice, expression and
    repeat) independent.  A process-local ``random.Random`` would make adding
    a row change every later choice, so all derivation is based on stable IDs.
    """
    digest = hashlib.sha256(("brain-semantic-matrix.v2|" + str(seed) + "|" +
                             "|".join(str(part) for part in parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _asset_for_role(role: str, catalog: dict[str, dict[str, Any]], roles: dict[str, Any], *, seed: int,
                    case_id: str, sample: int, exclude_names: set[str] | None = None) -> dict[str, Any] | None:
    spec = roles.get(role) if isinstance(roles, dict) else None
    candidates = list(spec.get("candidates", [])) if isinstance(spec, dict) else []
    kind = str(spec.get("kind", "")).casefold() if isinstance(spec, dict) else ""

    def kind_matches(item: dict[str, Any]) -> bool:
        """Keep role constraints authoritative at compile time.

        The old compiler checked ``kind`` against the category index, while
        the v2 compiler initially only matched semantic names.  That allowed
        a malformed role file to select a table as ``object_a`` or a fruit as
        ``surface_1`` and then report a misleading semantic test result.  The
        catalog is the only source of category truth; unknown categories are
        rejected for constrained roles rather than guessed.
        """
        if item.get("type", item.get("asset_type", "model")) != "model":
            return False
        category = str(item.get("category") or "").casefold()
        if kind == "surface":
            # The configured primary table is intentionally a passive
            # platform asset.  It is valid as a support role even though it
            # must never be generated as an ordinary object.
            return category in {"surface", "support_surface", "table"}
        if item.get("passive_or_platform"):
            return False
        if kind == "container":
            return category == "container"
        if kind == "pickable":
            # Pickable role samples may include ordinary containers (a basket
            # can itself be manipulated), but never the support surface.  This
            # mirrors the historical role contract without hard-coding model
            # names or treating an unknown category as a surface.
            return category not in {"surface", "support_surface", "table", "furniture"}
        return True

    if not catalog:
        return {"asset_key": candidates[0] if candidates else role, "display_name": candidates[0] if candidates else role, "semantic_name": candidates[0] if candidates else role}
    matching = [item for key, item in sorted(catalog.items())
                if item.get("semantic_name") in candidates and kind_matches(item)]
    exclude_names = exclude_names or set()
    distinct = [item for item in matching
                if str(item.get("semantic_name", "")).casefold() not in exclude_names]
    if distinct:
        matching = distinct
    if not matching:
        # Falling back to an arbitrary ordinary model makes a broken role
        # definition look like a valid semantic test and changes the oracle.
        # v2 requires the catalog/role contract to fail at compile time.
        raise BatchMatrixError(f"semantic_matrix_v2_role_candidates_missing:{role}:{','.join(candidates)}")
    return matching[_stable_index(seed, case_id, role, str(sample), size=len(matching))]


def _role_mapping(case: dict[str, Any], catalog, roles, seed: int, sample: int,
                  inherited: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Resolve roles while retaining identities inherited from the parent case.

    A child may introduce a new role (T02 adds ``object_b``), but it must not
    silently redraw ``object_a``.  This is important for language variants:
    all expressions in a branch must operate on the exact same asset and
    physical baseline.
    """
    result = {}
    inherited = inherited or {}
    for role_col in ("role_a", "role_b", "placement_1", "placement_2", "surface_1"):
        role = _cell(case.get(role_col))
        if role:
            if role in inherited:
                result[role] = deepcopy(inherited[role])
            else:
                # The two operation slots are intended to denote distinct
                # objects.  Exclude an already selected semantic name when a
                # different candidate exists, while allowing a one-candidate
                # catalog to remain explicit rather than fabricating an asset.
                exclude = ({str(item.get("semantic_name", "")).casefold() for item in result.values()}
                           if role in {"object_b", "placement_2"} else set())
                result[role] = _asset_for_role(role, catalog, roles, seed=seed,
                                               case_id=str(case["case_id"]), sample=sample,
                                               exclude_names=exclude)
    return {key: value for key, value in result.items() if value is not None}


def _render_v2(template: str, roles: dict[str, dict[str, Any]]) -> str:
    values = {role: value.get("display_name") or value.get("semantic_name") or role for role, value in roles.items()}
    return _render(template, values)


def _parent_variants(spec, case: dict[str, Any], *, seed: int):
    parent = case.get("parent_case_id")
    if not parent:
        return [None]
    variants = spec["variants_by_case"][parent]
    policy = case["parent_variant_policy"]
    if policy == "fixed":
        return [next(item for item in variants if item["variant_id"] == _cell(case.get("parent_variant_id")))]
    if policy == "all":
        return list(variants)
    # ``seed`` means one stable parent expression, not the old length slice.
    return [variants[_stable_index(seed, str(case["case_id"]), "parent_variant", size=len(variants))]]


def apply_matrix_run_profile(spec: dict[str, Any], run_profile: str) -> dict[str, Any]:
    """Apply a named execution profile to the in-memory matrix specification.

    Compilation and campaign execution must use the same effective parent DAG.
    In particular, ``independent_first_five`` deliberately removes the
    T01→T02..T05 dependency so those rows can be evaluated against their own
    fixtures.  Keeping this transformation in one helper prevents the
    compiler from emitting independent sessions while the campaign still
    reads the unmodified workbook and skips them as failed children.
    """
    if run_profile in {"independent_first_five", "center_empty"}:
        for case in spec["cases"]:
            if str(case["case_id"]) in {"T01", "T02", "T03", "T04", "T05"}:
                case["parent_case_id"] = None
                case["parent_variant_policy"] = "none"
                case["parent_variant_id"] = None
            if run_profile == "center_empty" and str(case["case_id"]) == "T02":
                case["fixture_id"] = "center_empty"
    return spec


def compile_semantic_matrix_v2(matrix: str | Path, *, kind: str = "generated_edit",
                               asset_roles: str | Path | None = None,
                               asset_catalog: str | Path | None = None,
                               seed: int = 0, output: str | Path | None = None,
                               strict_counts: bool = False, run_profile: str = "default"):
    spec = read_semantic_matrix_v2(matrix, strict_counts=strict_counts)
    if kind not in {"generated_edit", "known_scene"}:
        raise BatchMatrixError(f"semantic_matrix_v2_kind_invalid:{kind}")
    roles = json.loads(Path(asset_roles).read_text(encoding="utf-8")) if asset_roles else {}
    catalog, declared_catalog_revision = (load_asset_catalog_document(asset_catalog)
                                          if asset_catalog else ({}, None))
    catalog_payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    catalog_revision = (declared_catalog_revision or
                        ("sha256:" + hashlib.sha256(catalog_payload.encode("utf-8")).hexdigest()))
    # Profiles alter execution topology only; never mutate the reader's source
    # rows in place because callers may reuse ``spec`` for a second compile.
    apply_matrix_run_profile(spec, run_profile)
    sessions, manifest_rows = [], []
    # Matrix rows are normally topologically ordered.  Building this map by
    # recursive resolution also makes a valid workbook robust to harmless row
    # reordering while retaining the explicit parent DAG validation.
    cases_by_id = {str(case["case_id"]): case for case in spec["cases"]}
    role_maps_by_case: dict[str, list[dict[str, dict[str, Any]]]] = {}
    asset_seeds_by_case: dict[str, list[int]] = {}

    def role_maps(case_id: str) -> list[dict[str, dict[str, Any]]]:
        if case_id in role_maps_by_case:
            return role_maps_by_case[case_id]
        case = cases_by_id[case_id]
        parent_id = case.get("parent_case_id")
        parent_maps = role_maps(str(parent_id)) if parent_id else []
        samples = int(case["asset_samples"])
        values = []
        seeds = []
        for sample in range(1, samples + 1):
            inherited = parent_maps[(sample - 1) % len(parent_maps)] if parent_maps else None
            # Keep the root seed visible but derive a per-sample seed that is
            # independent of case iteration order.  Inherited roles are copied
            # from ``inherited`` and are therefore not redrawn here.
            sample_seed = _derived_seed(seed, "asset", case_id, str(sample))
            values.append(_role_mapping(case, catalog, roles, sample_seed, sample,
                                        inherited=inherited))
            seeds.append(sample_seed)
        role_maps_by_case[case_id] = values
        asset_seeds_by_case[case_id] = seeds
        return values

    for case in spec["cases"]:
        case_id = str(case["case_id"])
        variants = spec["variants_by_case"][case_id]
        parent_variants = _parent_variants(spec, case, seed=seed)
        for sample in range(1, int(case["asset_samples"]) + 1):
            role_map = role_maps(case_id)[sample - 1]
            asset_seed = asset_seeds_by_case[case_id][sample - 1]
            for parent_variant in parent_variants:
                parent_instruction = None if parent_variant is None else _render_v2(parent_variant["instruction_template"], role_map)
                for variant in variants:
                    instruction = _render_v2(variant["instruction_template"], role_map)
                    instructions = [instruction] if parent_instruction is None else [parent_instruction, instruction]
                    for repeat in range(1, int(case["repeats_per_variant"]) + 1):
                        name = f"{case_id}-{variant['variant_id']}-a{sample:02d}-r{repeat:02d}"
                        item = {
                            "name": name, "scene": None, "instructions": instructions,
                            "test_id": case_id, "variant_id": variant["variant_id"],
                            "flow_id": case_id, "parent_flow_id": case.get("parent_case_id"),
                            "difficulty": case.get("difficulty"), "category": case.get("name"),
                            "random_seed": seed,
                            "equivalence_group": variant.get("equivalence_group"),
                            "parent_case_id": case.get("parent_case_id"),
                            "parent_variant_id": parent_variant.get("variant_id") if parent_variant else None,
                            "fixture_id": case.get("fixture_id"), "asset_seed": asset_seed,
                            "repeat_index": repeat, "asset_role_mapping": role_map,
                            "expected_outcome": variant["expected_outcome"],
                            "expected_error_codes": variant["expected_json_value"].get(
                                "allowed_error_codes",
                                variant["expected_json_value"].get("error_codes", [])),
                            "expected_json": variant["expected_json_value"],
                            "precondition": variant.get("precondition"),
                            "coverage_tag": variant.get("equivalence_group"),
                            "scene_basis": ("empty_bootstrap" if case.get("fixture_id") in {"workspace_empty", "center_empty"}
                                            else "preset" if case.get("fixture_id") else "current"),
                            "requires_visual": False,
                            "expected_scene_change": (
                                "changed" if variant["expected_outcome"] in {"scene_updated", "robot_setup_updated"}
                                else "query_only" if variant["expected_outcome"] == "answered"
                                else "unchanged"),
                            "assertion_profile": variant["expected_json_value"].get(
                                "assertion_profile", variant.get("equivalence_group")),
                            "expected_assertions": variant["expected_json_value"],
                            "catalog_scenario": variant.get("catalog_scenario"),
                            "catalog_revision": catalog_revision,
                            "seed_algorithm": "sha256(brain-semantic-matrix.v2|root|axis|stable-ids)",
                        }
                        sessions.append(item)
                        manifest_rows.append({"session": name, "case_id": case_id, "variant_id": variant["variant_id"],
                                              "parent_variant_id": item["parent_variant_id"], "asset_seed": asset_seed,
                                              "asset_role_mapping": role_map, "source_row": variant["_row"],
                                              "catalog_scenario": variant.get("catalog_scenario"),
                                              "expected_outcome": variant["expected_outcome"]})
    manifest = {"schema": "brain-semantic-matrix.v2", "schema_version": 2, "matrix_version": 2,
                "kind": kind, "matrix": str(Path(matrix).resolve()),
                "run_profile": run_profile, "seed": seed,
                "asset_seed_algorithm": "sha256(brain-semantic-matrix.v2|root|asset|case_id|sample)[:8]",
                "case_count": len(spec["cases"]),
                "variant_count": len(spec["variants"]), "invariant_count": spec["invariant_count"],
                "session_count": len(sessions),
                "seed_algorithm": "sha256(brain-semantic-matrix.v2|root|axis|stable-ids)",
                "catalog_revision": catalog_revision,
                "catalog_revision_source": ("derived_ols_snapshot" if declared_catalog_revision
                                             else "assets_mapping_digest"),
                "rows": manifest_rows,
                "catalog_keys": sorted(catalog),
                "coverage": {"enabled_variants": len(spec["variants"]),
                             "compiled_sessions": len(sessions),
                             "invariants": spec["invariant_count"]}}
    document = {"kind": "sessions", "schema_version": 2, "matrix_version": 2, "sessions": sessions}
    if output:
        destination = Path(output).resolve(); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destination.with_name(destination.stem + "_compile_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document, manifest

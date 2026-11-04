"""Importer/compiler for the ``brain-semantic-matrix.v2`` workbook.

This module is intentionally separate from the historical v1 matrix reader.
The v2 workbook has one feature per row and one complete expression per row in
the ``variants`` sheet.  It never interprets a bare variant as a value and it
never truncates a row to ``sample_count``.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .batch_matrix import BatchMatrixError, _cell, _enabled, _fields, _render, load_asset_catalog


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
V2_PLACEHOLDERS = {"object_a", "object_b", "placement_1", "placement_2", "surface_1"}


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
    if not catalog:
        return {"asset_key": candidates[0] if candidates else role, "display_name": candidates[0] if candidates else role, "semantic_name": candidates[0] if candidates else role}
    matching = [item for key, item in sorted(catalog.items())
                if item.get("semantic_name") in candidates and not item.get("passive_or_platform")]
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


def compile_semantic_matrix_v2(matrix: str | Path, *, kind: str = "generated_edit",
                               asset_roles: str | Path | None = None,
                               asset_catalog: str | Path | None = None,
                               seed: int = 0, output: str | Path | None = None,
                               strict_counts: bool = False, run_profile: str = "default"):
    spec = read_semantic_matrix_v2(matrix, strict_counts=strict_counts)
    if kind not in {"generated_edit", "known_scene"}:
        raise BatchMatrixError(f"semantic_matrix_v2_kind_invalid:{kind}")
    roles = json.loads(Path(asset_roles).read_text(encoding="utf-8")) if asset_roles else {}
    catalog = load_asset_catalog(asset_catalog) if asset_catalog else {}
    catalog_payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    catalog_revision = "sha256:" + hashlib.sha256(catalog_payload.encode("utf-8")).hexdigest()
    # Profiles alter execution topology only; never mutate the reader's source
    # rows in place because callers may reuse ``spec`` for a second compile.
    if run_profile in {"independent_first_five", "center_empty"}:
        for case in spec["cases"]:
            if str(case["case_id"]) in {"T01", "T02", "T03", "T04", "T05"}:
                case["parent_case_id"] = None
                case["parent_variant_policy"] = "none"
                case["parent_variant_id"] = None
            if run_profile == "center_empty" and str(case["case_id"]) == "T02":
                # The official T02 center expression is a positive region
                # check, so it needs the declared empty-table baseline rather
                # than T01's occupied center.  The campaign still records this
                # profile decision in its manifest.
                case["fixture_id"] = "center_empty"
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
                            "catalog_revision": catalog_revision,
                            "seed_algorithm": "sha256(brain-semantic-matrix.v2|root|axis|stable-ids)",
                        }
                        sessions.append(item)
                        manifest_rows.append({"session": name, "case_id": case_id, "variant_id": variant["variant_id"],
                                              "parent_variant_id": item["parent_variant_id"], "asset_seed": asset_seed,
                                              "asset_role_mapping": role_map, "source_row": variant["_row"],
                                              "expected_outcome": variant["expected_outcome"]})
    manifest = {"schema": "brain-semantic-matrix.v2", "kind": kind, "matrix": str(Path(matrix).resolve()),
                "run_profile": run_profile, "seed": seed,
                "asset_seed_algorithm": "sha256(brain-semantic-matrix.v2|root|asset|case_id|sample)[:8]",
                "case_count": len(spec["cases"]),
                "variant_count": len(spec["variants"]), "invariant_count": spec["invariant_count"],
                "session_count": len(sessions),
                "seed_algorithm": "sha256(brain-semantic-matrix.v2|root|axis|stable-ids)",
                "catalog_revision": catalog_revision, "rows": manifest_rows,
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

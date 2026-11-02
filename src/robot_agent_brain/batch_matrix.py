"""Excel-backed batch matrix compiler.

The compiler deliberately has no dependency on a running Brain service.  It
turns a small, human-maintained workbook into the JSON session format used by
``robot-brain batch`` and writes a manifest describing every deterministic
choice made while expanding the matrix.
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any, Iterable


GENERATED_COLUMNS = (
    "enabled", "flow_id", "parent_flow_id", "difficulty", "stage", "round_index",
    "category", "sample_count", "role_a", "role_b", "placement_1", "placement_2",
    "instruction_template", "variants", "branch_policy", "notes",
)
KNOWN_COLUMNS = (
    "enabled", "scene_name", "difficulty", "category", "sample_count",
    "instruction_template", "variants", "role_a", "role_b", "round_index", "notes",
)
PLACEHOLDERS = {"object_a", "object_b", "placement_1", "placement_2", "surface_1",
                "color", "color_phrase", "direction", "distance"}


class BatchMatrixError(ValueError):
    """A user-correctable workbook error with a precise source location."""


def _openpyxl():
    try:
        import openpyxl  # type: ignore
    except ModuleNotFoundError as exc:
        raise BatchMatrixError("batch_matrix_requires_openpyxl") from exc
    return openpyxl


def _cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _enabled(value: Any) -> bool:
    return _cell(value).casefold() in {"1", "true", "yes", "y", "on", "启用", "是"}


def _variants(value: Any) -> list[str]:
    return [item.strip() for item in _cell(value).split("|") if item.strip()]


def _row_error(sheet: str, row: int, column: str, message: str) -> BatchMatrixError:
    return BatchMatrixError(f"batch_matrix_invalid:{sheet}!{column}{row}: {message}")


def read_matrix(path: str | Path, kind: str) -> list[dict[str, Any]]:
    """Read and validate the ``matrix`` sheet of an Excel workbook."""
    if kind not in {"generated_edit", "known_scene"}:
        raise BatchMatrixError(f"batch_matrix_kind_invalid:{kind}")
    source = Path(path).resolve()
    if not source.is_file():
        raise BatchMatrixError(f"batch_matrix_not_found:{source}")
    book = _openpyxl().load_workbook(source, read_only=True, data_only=True)
    if "matrix" not in book.sheetnames:
        raise BatchMatrixError("batch_matrix_sheet_missing:matrix")
    sheet = book["matrix"]
    try:
        header_row = next(sheet.iter_rows(min_row=1, max_row=1))
    except StopIteration as exc:
        raise BatchMatrixError("batch_matrix_sheet_empty:matrix") from exc
    headers = [_cell(item.value) for item in header_row]
    required = GENERATED_COLUMNS if kind == "generated_edit" else KNOWN_COLUMNS
    missing = [name for name in required if name not in headers]
    if missing:
        raise BatchMatrixError("batch_matrix_columns_missing:" + ",".join(missing))
    positions = {name: headers.index(name) for name in headers}
    rows: list[dict[str, Any]] = []
    for row_no, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        values = [_cell(cells[positions[name]] if positions[name] < len(cells) else "") for name in headers]
        if not any(values) or not _enabled(values[positions["enabled"]]):
            continue
        item = {name: values[positions[name]] for name in required}
        if not item.get("instruction_template"):
            raise _row_error("matrix", row_no, "instruction_template", "required")
        item["_row"] = row_no
        item["variants_list"] = _variants(item.get("variants"))
        if not item["variants_list"]:
            raise _row_error("matrix", row_no, "variants", "at least one variant is required")
        try:
            item["round_index"] = int(item.get("round_index") or 1)
            item["sample_count"] = int(item.get("sample_count") or 1)
        except ValueError as exc:
            raise _row_error("matrix", row_no, "round_index", "must be an integer") from exc
        if item["round_index"] < 1 or item["round_index"] > 10:
            raise _row_error("matrix", row_no, "round_index", "must be 1..10")
        if item["sample_count"] < 1:
            raise _row_error("matrix", row_no, "sample_count", "must be positive")
        if kind == "generated_edit":
            if item.get("stage") not in {"generate", "edit"}:
                raise _row_error("matrix", row_no, "stage", "must be generate or edit")
            if not item.get("flow_id"):
                raise _row_error("matrix", row_no, "flow_id", "required")
            policy = item.get("branch_policy") or "seed_parent"
            if policy not in {"seed_parent", "all_parents"}:
                raise _row_error("matrix", row_no, "branch_policy", "must be seed_parent or all_parents")
            item["branch_policy"] = policy
        rows.append(item)
    return rows


def _fields(template: str) -> set[str]:
    try:
        return {field for _, field, _, _ in Formatter().parse(template) if field}
    except ValueError as exc:
        raise BatchMatrixError(f"batch_matrix_template_invalid:{exc}") from exc


def _render(template: str, values: dict[str, Any]) -> str:
    unknown = _fields(template) - set(values)
    if unknown:
        raise BatchMatrixError("batch_matrix_template_placeholder_unknown:" + ",".join(sorted(unknown)))
    try:
        return template.format(**values).strip()
    except (KeyError, ValueError) as exc:
        raise BatchMatrixError(f"batch_matrix_template_invalid:{exc}") from exc


@dataclass(frozen=True)
class AssetChoice:
    name: str
    ref: str | None
    asset_type: str = "model"
    asset_id: int | None = None

    def manifest(self) -> dict[str, Any]:
        return {"semantic_name": self.name, "metadata_ref": self.ref,
                "type": self.asset_type, "id": self.asset_id}


def load_roles(path: str | Path) -> dict[str, dict[str, Any]]:
    source = Path(path).resolve()
    try:
        values = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BatchMatrixError(f"batch_asset_roles_not_found:{source}") from exc
    if not isinstance(values, dict):
        raise BatchMatrixError("batch_asset_roles_invalid")
    return values


def _asset_index(asset_root: Path | None) -> dict[str, list[int]]:
    if asset_root is None:
        return {}
    index = asset_root / "models" / "model_index.json"
    if not index.is_file():
        return {}
    value = json.loads(index.read_text(encoding="utf-8"))
    return {str(name): [int(i) for i in ids] for name, ids in (value.get("by_name") or {}).items()}


def resolve_role_choices(roles: dict[str, dict[str, Any]], *, seed: int,
                         asset_root: str | Path | None = None,
                         default_assets: dict[str, str] | None = None,
                         category_index: dict[str, str] | None = None) -> tuple[dict[str, AssetChoice], dict[str, Any]]:
    """Choose one candidate per role deterministically and return manifest data."""
    rng = random.Random(seed)
    index = _asset_index(Path(asset_root).resolve() if asset_root else None)
    choices: dict[str, AssetChoice] = {}
    manifest: dict[str, Any] = {"seed": seed, "roles": {}}
    for role, spec in roles.items():
        candidates = spec.get("candidates") if isinstance(spec, dict) else None
        if not isinstance(candidates, list) or not candidates or any(not isinstance(x, str) or not x.strip() for x in candidates):
            raise BatchMatrixError(f"batch_asset_role_invalid:{role}")
        candidate = candidates[rng.randrange(len(candidates))]
        ids = index.get(candidate, [])
        ref = (default_assets or {}).get(candidate)
        # An unambiguous OLS name can be represented without a config file.
        if ref is None and len(ids) == 1:
            ref = f"$LIBRARY_SERVER/{ids[0]}"
        if index and not ids:
            raise BatchMatrixError(f"batch_asset_role_candidate_missing:{role}:{candidate}")
        asset_id = None
        if ref and ref.rsplit("/", 1)[-1].isdigit():
            asset_id = int(ref.rsplit("/", 1)[-1])
        choice = AssetChoice(candidate, ref, "model", asset_id)
        category = (category_index or {}).get(f"model:{asset_id}") if asset_id is not None else None
        kind = spec.get("kind")
        allowed = {
            "pickable": {"fruit", "ball", "tool", "object", "toy", "container"},
            "container": {"container"},
            "surface": {"surface"},
        }.get(kind)
        if category and allowed and category not in allowed:
            raise BatchMatrixError(f"batch_asset_role_category_mismatch:{role}:{candidate}:{category}")
        choices[role] = choice
        manifest["roles"][role] = {"kind": spec.get("kind"), "candidates": candidates,
                                    "selected": choice.manifest()}
    return choices, manifest


def _instruction_variants(row: dict[str, Any], values: dict[str, Any]) -> list[str]:
    # A variant can be a complete alternative sentence or a simple value for a
    # placeholder.  Both forms are useful in a spreadsheet.
    template = row["instruction_template"]
    variants = row["variants_list"]
    rendered: list[str] = []
    for variant in variants:
        if variant.strip() in {f"{{{field}}}" for field in PLACEHOLDERS}:
            rendered.append(_render(template, values))
        elif "{" in variant:
            rendered.append(_render(variant, values))
        else:
            # Matrix authors may provide complete sentence alternatives (the
            # common known-scene form is ``苹果在篮子左边吗``).  Do not stuff
            # such a sentence into ``object_a`` merely because the base
            # template happens to contain that placeholder.
            sentence_markers = ("在", "吗", "旁边", "放", "增加", "移动", "改", "换", "渲染", "画", "左", "右", "前", "后", "上", "下")
            if any(marker in variant for marker in sentence_markers) and len(variant) > 4:
                rendered.append(variant)
                continue
            expanded = {**values, "color": variant, "color_phrase": variant,
                        "direction": variant, "distance": variant}
            fields = _fields(template)
            # A bare variant is a value for the first semantic placeholder in
            # the template.  This makes rows such as “增加一个 {object_a}”
            # useful for cycling apple/banana/baseball, while color and
            # direction rows naturally bind to their own fields.
            if "direction" in fields and variant in {"左", "右", "前", "后", "一点", "一些", "很多", "向左", "向右", "向前", "向后"}:
                expanded["direction"] = variant
            elif "distance" in fields and re.search(r"(?:\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m))", variant, re.I):
                expanded["distance"] = variant
            elif "color" in fields or "color_phrase" in fields:
                expanded["color"] = variant
                expanded["color_phrase"] = variant
            else:
                for field in ("object_a", "object_b", "placement_1", "placement_2", "surface_1"):
                    if field in fields:
                        expanded[field] = variant
                        break
            rendered.append(_render(template, expanded))
    return rendered


def _role_values(choices: dict[str, AssetChoice]) -> dict[str, str]:
    # OLS uses stable English semantic IDs; instructions are user-facing and
    # should use the same common Chinese vocabulary as the Brain prompts.
    display = {
        "apple": "苹果", "banana": "香蕉", "baseball": "棒球", "pen": "钢笔",
        "marker": "马克笔", "basket": "篮子", "tray": "托盘", "sugar_box": "糖盒",
        "mug": "杯子", "table": "桌子", "coffee_table": "茶几", "cabinet": "柜子",
        "drawer": "抽屉", "microwave": "微波炉", "bottle": "瓶子", "button": "按钮",
        "can": "罐子", "rubiks_cube": "魔方", "test_tube": "试管",
    }
    return {role: display.get(choice.name, choice.name) for role, choice in choices.items()}


def _scene_lookup(asset_root: Path | None) -> dict[str, str]:
    if asset_root is None:
        return {}
    index = asset_root / "scenes" / "scene_index.json"
    if not index.is_file():
        return {}
    items = json.loads(index.read_text(encoding="utf-8"))
    return {item["name"]: str(asset_root / "scenes" / str(item["id"]) / (item["name"] + ".json"))
            for item in items if isinstance(item, dict) and item.get("name") and item.get("id") is not None}


def _validate_template_placeholders(rows: Iterable[dict[str, Any]], kind: str) -> None:
    for row in rows:
        unknown = _fields(row["instruction_template"]) - PLACEHOLDERS
        if unknown:
            raise _row_error("matrix", row["_row"], "instruction_template",
                             "unknown placeholders: " + ",".join(sorted(unknown)))
        for variant in row["variants_list"]:
            unknown = _fields(variant) - PLACEHOLDERS
            if unknown:
                raise _row_error("matrix", row["_row"], "variants",
                                 "unknown placeholders: " + ",".join(sorted(unknown)))
    if kind == "generated_edit":
        flows = {row["flow_id"] for row in rows}
        for row in rows:
            parent = row.get("parent_flow_id")
            if parent and parent not in flows:
                raise _row_error("matrix", row["_row"], "parent_flow_id", f"unknown flow {parent}")


def compile_matrix(matrix: str | Path, *, kind: str, asset_roles: str | Path | None = None,
                   seed: int = 0, output: str | Path | None = None,
                   asset_root: str | Path | None = None,
                   default_assets: dict[str, str] | None = None,
                   category_index: dict[str, str] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile a workbook, returning ``(session_document, manifest)``."""
    rows = read_matrix(matrix, kind)
    _validate_template_placeholders(rows, kind)
    roles = load_roles(asset_roles) if asset_roles else {}
    choices, manifest = resolve_role_choices(roles, seed=seed, asset_root=asset_root,
                                              default_assets=default_assets, category_index=category_index)
    values = _role_values(choices)
    sessions: list[dict[str, Any]] = []
    matrix_path = Path(matrix).resolve()
    if kind == "known_scene":
        scenes = _scene_lookup(Path(asset_root).resolve() if asset_root else None)
        for row in rows:
            scene = scenes.get(row["scene_name"])
            if scene is None:
                raise _row_error("matrix", row["_row"], "scene_name", f"unknown scene {row['scene_name']}")
            if output:
                scene = os.path.relpath(scene, Path(output).resolve().parent)
            instructions = _instruction_variants(row, values)
            for variant_index, instruction in enumerate(instructions, 1):
                count = row["sample_count"]
                for sample in range(1, count + 1):
                    name = f"{row['scene_name']}-{row['difficulty']}-{row['category']}-{row['_row']}-{variant_index}-{sample}"
                    sessions.append({"name": name, "scene": scene, "instructions": [instruction],
                                     "difficulty": row["difficulty"], "capabilities": [row["category"]],
                                     "category": row["category"], "random_seed": seed,
                                     "asset_role_mapping": manifest["roles"]})
                    manifest.setdefault("rows", []).append({"sheet": "matrix", "row": row["_row"],
                        "session": name, "asset_role_mapping": manifest["roles"], "scene_name": row["scene_name"]})
    else:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["flow_id"], []).append(row)
        # Preserve parent-first order while rejecting cycles.
        visiting: set[str] = set()
        built: dict[str, list[dict[str, Any]]] = {}

        def build(flow: str) -> list[dict[str, Any]]:
            if flow in built:
                return built[flow]
            if flow in visiting:
                raise BatchMatrixError(f"batch_matrix_flow_cycle:{flow}")
            visiting.add(flow)
            flow_rows = sorted(grouped[flow], key=lambda row: (row["round_index"], row["_row"]))
            parents = {row.get("parent_flow_id") for row in flow_rows if row.get("parent_flow_id")}
            if len(parents) > 1:
                raise BatchMatrixError(f"batch_matrix_multiple_parents:{flow}")
            prefixes = build(next(iter(parents))) if parents else [{"instructions": [], "parent": None}]
            policy = flow_rows[0].get("branch_policy") or "seed_parent"
            if parents and policy == "seed_parent" and len(prefixes) > 1:
                # Stable parent selection is part of the manifest's seed
                # contract; all_parents deliberately retains every prefix.
                prefixes = [prefixes[seed % len(prefixes)]]
            generated = prefixes
            for row in flow_rows:
                # Each variant is an independent deterministic branch.  The
                # sample_count below cycles over these branches, so a row with
                # four colour phrasings exercises all four rather than silently
                # selecting one and repeating it for every sample.
                options = _instruction_variants(row, values)
                expanded: list[dict[str, Any]] = []
                for prefix_index, prefix in enumerate(generated, 1):
                    for option_index, option in enumerate(options, 1):
                        expanded.append({
                            "instructions": [*prefix["instructions"], option],
                            "parent": prefix.get("parent") or flow,
                            "variant_index": (prefix_index, option_index),
                        })
                generated = expanded
            built[flow] = generated
            visiting.remove(flow)
            return generated

        for flow in grouped:
            flows = build(flow)
            rows_for_flow = grouped[flow]
            count = max(row["sample_count"] for row in rows_for_flow)
            for sample_index in range(1, count + 1):
                item = flows[(sample_index - 1) % len(flows)]
                name = f"{flow}-{rows_for_flow[0]['difficulty']}-{sample_index:02d}"
                sessions.append({"name": name, "scene": None, "instructions": item["instructions"],
                                 "difficulty": rows_for_flow[0]["difficulty"],
                                 "capabilities": sorted({row["category"] for row in rows_for_flow}),
                                 "flow_id": flow, "parent_flow_id": rows_for_flow[0].get("parent_flow_id"),
                                 "category": rows_for_flow[0]["category"], "random_seed": seed,
                                 "asset_role_mapping": manifest["roles"]})
                manifest.setdefault("rows", []).append({"sheet": "matrix", "row": rows_for_flow[0]["_row"],
                    "session": name, "flow_id": flow, "parent_flow_id": rows_for_flow[0].get("parent_flow_id"),
                    "asset_role_mapping": manifest["roles"]})
    document = {"sessions": sessions}
    manifest.update({"matrix": str(matrix_path), "kind": kind, "session_count": len(sessions)})
    if output:
        out = Path(output).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out.with_name(out.stem + "_compile_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document, manifest


def compile_from_cli(*, matrix: str, kind: str, asset_roles: str | None, seed: int,
                     output: str, asset_root: str | None = None, config: str | None = None) -> Path:
    defaults: dict[str, str] = {}
    category_index: dict[str, str] = {}
    # The documented command intentionally keeps configuration optional.  In a
    # checkout, use the WebEditor integration config when present so scene and
    # OLS name validation works without repeating a machine-specific path.
    if config is None:
        candidate = Path.cwd() / "config" / "webeditor.json"
        if candidate.is_file():
            config = str(candidate)
    if config:
        cfg = json.loads(Path(config).read_text(encoding="utf-8"))
        base = Path(config).resolve().parent
        root = cfg.get("asset_library_root")
        if root and not Path(root).is_absolute():
            root = str((base / root).resolve())
        asset_root = asset_root or root
        defaults = cfg.get("default_scene_edit_assets") or {}
        category_file = cfg.get("asset_category_index")
        if category_file:
            category_path = Path(category_file)
            if not category_path.is_absolute():
                category_path = base / category_path
            if category_path.is_file():
                category_index = json.loads(category_path.read_text(encoding="utf-8"))
    document, _ = compile_matrix(matrix, kind=kind, asset_roles=asset_roles, seed=seed,
                                  output=output, asset_root=asset_root, default_assets=defaults,
                                  category_index=category_index)
    return Path(output).resolve()

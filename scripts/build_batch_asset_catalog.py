#!/usr/bin/env python3
"""Build the human-readable batch-test asset catalog from an OLS export.

The Excel matrices refer to ``asset_key`` values, never to OLS numeric IDs.
This file is a derived index and may be regenerated whenever the OLS resource
version changes.  It does not modify the OLS tree.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DISPLAY_NAMES = {
    "apple": "苹果", "banana": "香蕉", "baseball": "棒球", "basket": "篮子",
    "pen": "钢笔", "screwdriver": "螺丝刀", "gum_bottle": "胶瓶",
    "cream": "护肤霜", "marker": "马克笔", "test_tube_rack": "试管架",
    "mug": "杯子", "rubiks_cube": "魔方", "school_bell": "铃铛",
    "tray": "托盘", "coffee_table": "茶几", "sugar_box": "糖盒",
    "test_tube": "试管", "doll": "玩偶", "drawer": "抽屉",
    "cabinet": "柜子", "table": "桌子", "microwave": "微波炉",
    "bottle": "瓶子", "button": "按钮", "can": "罐子",
}

PASSIVE = {"drawer", "cabinet", "microwave", "button"}
SURFACES = {"table", "coffee_table"}
CONTAINERS = {"basket", "tray", "sugar_box", "mug", "test_tube_rack", "drawer", "cabinet", "microwave", "bottle", "can"}


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return value or "asset"


def _tags(semantic: dict) -> list[str]:
    raw = semantic.get("tag", "")
    if isinstance(raw, list):
        values = raw
    else:
        values = re.split(r"[,;]", str(raw))
    return [_slug(item) for item in values if str(item).strip()]


def _category(name: str, model_id: int, category_index: dict[str, str]) -> str:
    configured = category_index.get(f"model:{model_id}")
    if configured:
        return configured
    if name in SURFACES:
        return "surface"
    if name in PASSIVE:
        return "passive"
    if name in CONTAINERS:
        return "container"
    return "object"


def build_catalog(root: Path) -> dict:
    index_path = root / "models" / "model_index.json"
    if not index_path.is_file():
        raise SystemExit(f"batch_asset_catalog_ols_index_missing:{index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    category_path = Path(__file__).resolve().parents[1] / "config" / "webeditor_categories.json"
    category_index = json.loads(category_path.read_text(encoding="utf-8")) if category_path.is_file() else {}
    version_path = root / "VERSION.txt"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "unknown"
    assets = []
    used: dict[str, int] = {}
    for raw_id, name in sorted((index.get("by_id") or {}).items(), key=lambda item: int(item[0])):
        model_id = int(raw_id)
        metadata_path = root / "models" / str(model_id) / f"{name}.json"
        if not metadata_path.is_file():
            raise SystemExit(f"batch_asset_catalog_metadata_missing:model:{model_id}:{metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        semantic = metadata.get("semantic_properties") or {}
        physical = metadata.get("physical_properties") or {}
        tags = _tags(semantic)
        base = _slug(name) + ("_" + "_".join(tags) if tags else "")
        used[base] = used.get(base, 0) + 1
        key = base if used[base] == 1 else f"{base}_variant{used[base]}"
        category = _category(name, model_id, category_index)
        passive = name in PASSIVE or (metadata_path.parent / f"{name}.urdf").is_file()
        if name in PASSIVE:
            edit_scope = ["query", "capability_boundary"]
        else:
            edit_scope = ["add", "remove", "replace", "translate", "move_relative", "rotate", "color", "query"]
            if bool(semantic.get("scalable")):
                edit_scope.append("scale")
        assets.append({
            "asset_key": key,
            "semantic_name": str(semantic.get("object_name") or name),
            "display_name": DISPLAY_NAMES.get(name, name),
            "metadata_ref": f"$LIBRARY_SERVER/{model_id}",
            "model_id": model_id,
            "category": category,
            "tags": tags,
            "scalable": bool(semantic.get("scalable")),
            "scale_range": physical.get("scale"),
            "has_urdf": bool((metadata_path.parent / f"{name}.urdf").is_file()),
            "passive_or_platform": passive,
            "edit_scope": edit_scope,
            "source_metadata": f"models/{model_id}/{name}.json",
        })
    return {
        "schema_version": 1,
        "source": {"resource_version": version, "model_count": len(assets)},
        "assets": assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="OLS data directory")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--brain-config",
        help=("Brain config used to derive the complete runtime catalog revision. "
              "When omitted, the catalog remains a legacy assets-only index."),
    )
    args = parser.parse_args()
    catalog = build_catalog(Path(args.root).resolve())
    if args.brain_config:
        # Use the same public adapter snapshot as the running Brain instead of
        # inventing a second digest algorithm in this build helper.  The
        # config is only read; neither OLS nor the derived geometry cache is
        # modified.
        try:
            from robot_agent_brain.config import BrainConfig
            config = BrainConfig.load(args.brain_config)
            configured_root = Path(config.asset_library_root or "").resolve()
            source_root = Path(args.root).resolve()
            if configured_root != source_root:
                raise SystemExit(
                    "batch_asset_catalog_root_mismatch:"
                    f"config={configured_root}:root={source_root}"
                )
            adapter = config.load_assets()
            snapshot = adapter.catalog_snapshot(
                aliases=None, registered_profiles=list(config.robot_profiles.profiles)
            )
            catalog["catalog_revision"] = snapshot.revision
            catalog["source"]["catalog_revision"] = snapshot.revision
            catalog["source"]["catalog_revision_source"] = "BrainConfig.load_assets"
        except ImportError as exc:
            raise SystemExit("batch_asset_catalog_brain_package_missing") from exc
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

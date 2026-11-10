#!/usr/bin/env python3
"""Build deterministic, test-only Scene v1 fixtures for the semantic C7 matrix.

The matrix deliberately keeps fixture construction outside the Qwen turns.  A
fixture is therefore a small, auditable scene document derived from a real OLS
platform scene; it is never written back to OLS and is not a production asset.
The campaign runner accepts the resulting directory with ``--fixture-dir``.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def _component(obj: dict, kind: str) -> dict | None:
    for component in obj.get("components", []):
        if component.get("component_type") == kind:
            return component.get("properties") or {}
    return None


def _set_component(obj: dict, kind: str, properties: dict) -> None:
    for component in obj.get("components", []):
        if component.get("component_type") == kind:
            component["properties"] = properties
            return
    obj.setdefault("components", []).append({"component_type": kind, "properties": properties})


def _base_scene(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("objects"), list):
        raise ValueError(f"fixture_base_scene_invalid:{path}")
    # Do not carry a stale task version into a fixture.  Gateway assigns the
    # authoritative setup version when it adopts the document.
    value["scene_version"] = 1
    value["scene_sub_version"] = 0
    return value


def _table(scene: dict) -> tuple[int, dict]:
    for obj in scene["objects"]:
        semantic = _component(obj, "Semantic") or {}
        if semantic.get("category") in {"surface", "support_surface", "table"}:
            return int(obj["object_id_in_scene"]), obj
    raise ValueError("fixture_primary_table_missing")


def _new_id(scene: dict) -> int:
    return max((int(obj["object_id_in_scene"]) for obj in scene["objects"]), default=0) + 1


def _add(scene: dict, *, semantic: str, category: str, model_id: int,
         position: list[float], support: int, color: str | None = None) -> int:
    identifier = _new_id(scene)
    components = [
        {"component_type": "Transform", "properties": {
            "position": position, "quaternion_xyzw": [0, 0, 0, 1],
            "scale": [1, 1, 1], "parent": None,
        }},
        {"component_type": "MetadataRef", "properties": {
            "path": f"$LIBRARY_SERVER/{model_id}", "type": "model",
        }},
        {"component_type": "MeshRenderer", "properties": {}},
        {"component_type": "Semantic", "properties": {
            "semantic_name": semantic, "category": category, "support": support,
        }},
    ]
    if color:
        components[2]["properties"]["forceOverrideColor"] = color
    scene["objects"].append({
        "object_id_in_scene": identifier,
        "object_name_in_scene": semantic,
        "components": components,
    })
    return identifier


def _replace_model(obj: dict, *, semantic: str, category: str, model_id: int) -> None:
    _set_component(obj, "MetadataRef", {"path": f"$LIBRARY_SERVER/{model_id}", "type": "model"})
    value = _component(obj, "Semantic") or {}
    value.update({"semantic_name": semantic, "category": category})
    _set_component(obj, "Semantic", value)
    obj["object_name_in_scene"] = semantic


def build(base: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []

    # A marker is the seeded object_a for T01/T03/T04/T05/T07/T11/T12.
    center = _base_scene(base)
    table_id, table = _table(center)
    user_objects = [obj for obj in center["objects"]
                    if (_component(obj, "Semantic") or {}).get("category")
                    not in {"surface", "support", "robot", "camera", "light", "platform"}]
    if user_objects:
        _replace_model(user_objects[-1], semantic="marker", category="tool", model_id=10)
        transform = _component(user_objects[-1], "Transform") or {}
        transform["position"] = [0.0, 0.0, 0.61]
        _set_component(user_objects[-1], "Transform", transform)
        _set_component(user_objects[-1], "Semantic", {"semantic_name": "marker", "category": "tool", "support": table_id})
    for name, x, y in (("single_a_center", 0.0, 0.0), ("single_a_corner", -0.35, 0.25)):
        value = copy.deepcopy(center)
        obj = next((item for item in value["objects"] if item.get("object_name_in_scene") == "marker"), None)
        if obj is not None:
            transform = _component(obj, "Transform") or {}
            transform["position"] = [x, y, 0.61]
            _set_component(obj, "Transform", transform)
        target = output / f"{name}.json"
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.append(target)

    value = _base_scene(base)
    table_id, _ = _table(value)
    _add(value, semantic="banana", category="fruit", model_id=2, position=[-0.18, 0.0, 0.62], support=table_id)
    _add(value, semantic="baseball", category="ball", model_id=3, position=[0.18, 0.0, 0.62], support=table_id)
    target = output / "two_distinct_objects.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.append(target)

    value = _base_scene(base)
    table_id, _ = _table(value)
    for position, color in [([-0.28, 0.16, 0.62], "#FF0000"), ([0.0, -0.08, 0.62], "#FF0000"), ([0.28, 0.16, 0.62], "#0000FF")]:
        _add(value, semantic="apple", category="fruit", model_id=1, position=position, support=table_id, color=color)
    _add(value, semantic="mug", category="container", model_id=23, position=[0.0, -0.28, 0.65], support=table_id)
    target = output / "three_a_one_reference.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.append(target)

    value = _base_scene(base)
    table_id, _ = _table(value)
    _add(value, semantic="basket", category="container", model_id=4, position=[0.0, 0.0, 0.68], support=table_id)
    for name in ("scalable_a_center", "safety_scenarios"):
        target = output / f"{name}.json"
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.append(target)

    value = _base_scene(base)
    table_id, _ = _table(value)
    _add(value, semantic="apple", category="fruit", model_id=1, position=[-0.22, 0.0, 0.62], support=table_id)
    _add(value, semantic="baseball", category="ball", model_id=3, position=[0.22, 0.0, 0.62], support=table_id)
    target = output / "original_with_current_difference.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.append(target)

    value = _base_scene(base)
    table_id, _ = _table(value)
    _add(value, semantic="pen", category="tool", model_id=6, position=[-0.18, 0.0, 0.62], support=table_id)
    _add(value, semantic="pen", category="tool", model_id=5, position=[0.18, 0.0, 0.62], support=table_id)
    target = output / "ambiguous_two_a.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.append(target)

    for name in ("catalog_contract_fixture", "registered_robot_profiles"):
        target = output / f"{name}.json"
        target.write_text(json.dumps(_base_scene(base), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.append(target)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-scene", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    paths = build(Path(args.base_scene).resolve(), Path(args.output_dir).resolve())
    print(json.dumps({"fixtures": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

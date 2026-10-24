"""Validate final_models indexes/references and write an external geometry cache."""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from final_models_geometry import measured, contained


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def read_index(root, kind):
    base = Path(root) / ("models" if kind == "model" else "robots")
    filename = "model_index.json" if kind == "model" else "robot_index.json"
    index = json.loads((base / filename).read_text(encoding="utf-8"))
    if set(index) != {"by_name", "by_id", "category", "thumbnail"}:
        raise ValueError(f"{kind}_index_invalid")
    if {str(k): name for name, values in index["by_name"].items() for k in values} != index["by_id"]:
        raise ValueError(f"{kind}_index_inconsistent")
    return index


def metadata_cache(root, kind, index, errors):
    base = Path(root) / ("models" if kind == "model" else "robots")
    cache = {}
    for raw_id, name in index["by_id"].items():
        identifier = int(raw_id)
        directory = base / raw_id
        metadata = directory / f"{name}.json"
        manifest = directory / f"{name}_files.json"
        data = json.loads(metadata.read_text(encoding="utf-8"))
        semantic = data["semantic_properties"]
        if semantic.get("object_id") != identifier or semantic.get("object_name") != name:
            raise ValueError(f"metadata_identity_invalid:{kind}/{identifier}")
        files = json.loads(manifest.read_text(encoding="utf-8"))
        for relative in [files["metadata"], files["path"], files["thumbnail"], *files.get("reference", [])]:
            target = contained(Path(root), directory, relative)
            if target.suffix.lower() in {".obj", ".urdf"}:
                try:
                    measured(Path(root), target)
                except FileNotFoundError as exc:
                    errors.append(f"{target}: {exc}")
        dimensions = tuple(float(value) for value in data["geometric_properties"]["AABB"])
        if len(dimensions) != 3 or any(value <= 0 for value in dimensions):
            raise ValueError(f"metadata_aabb_invalid:{kind}/{identifier}")
        try:
            geometry = measured(Path(root), directory / files["path"])
        except FileNotFoundError as exc:
            errors.append(f"{directory / files['path']}: {exc}")
            # Geometry unavailable: preserve dimensions, report validation failure.
            geometry = None
        cache[f"{kind}:{identifier}"] = geometry or {
            "dimensions_m": list(dimensions),
            "local_aabb_min_m": None,
            "local_aabb_max_m": None,
        }
    return cache


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cache", default="config/final_models_geometry_cache.json")
    parser.add_argument("--manifest", help="Version-specific expected model/robot/scene ID lists")
    parser.add_argument("--joint-cache", help="External output for complete URDF joint inventory")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.cache).resolve()
    joint_output = Path(args.joint_cache).resolve() if args.joint_cache else None
    if output.is_relative_to(root) or (joint_output is not None and joint_output.is_relative_to(root)):
        raise ValueError("asset_derived_file_inside_library")
    before = tree_hash(root)
    models, robots = read_index(root, "model"), read_index(root, "robot")
    errors = []
    cache = {**metadata_cache(root, "model", models, errors), **metadata_cache(root, "robot", robots, errors)}
    scenes = json.loads((root / "scenes/scene_index.json").read_text(encoding="utf-8"))
    expected = json.loads(Path(args.manifest).read_text(encoding="utf-8")) if args.manifest else {
        "model_ids": list(range(1,30)), "robot_ids": list(range(1,15)), "scene_ids": list(range(1,6))}
    if (set(models["by_id"]) != {str(i) for i in expected["model_ids"]}
            or set(robots["by_id"]) != {str(i) for i in expected["robot_ids"]}
            or len(scenes) != len(expected["scene_ids"]) or {item["id"] for item in scenes} != set(expected["scene_ids"])):
        raise ValueError("final_models_coverage_invalid")
    joints = {}
    # Keep a typed inventory for every URDF-backed namespace.  New OLS scenes
    # use RobotDriver on passive model assets (cabinet, drawer, microwave,
    # button, bottle), so limiting this cache to robots makes valid scenes
    # fail during web validation.
    for kind, index in (("model", models), ("robot", robots)):
        directory_name = "models" if kind == "model" else "robots"
        for identifier, name in index["by_id"].items():
            directory = root / directory_name / identifier
            files = json.loads((directory / f"{name}_files.json").read_text(encoding="utf-8"))
            entrance = contained(root, directory, files["path"])
            if entrance.suffix.lower() == ".urdf":
                document = ET.parse(entrance).getroot()
                joints[f"{kind}:{identifier}"] = {
                    "joints": sorted(n.attrib["name"] for n in document.findall("joint")),
                    "links": sorted(n.attrib["name"] for n in document.findall("link")),
                }
    for item in scenes:
        path = contained(root, root / "scenes", f"{item['id']}/{item['name']}.json")
        scene = json.loads(path.read_text(encoding="utf-8"))
        for obj in scene["objects"]:
            for component in obj["components"]:
                if component["component_type"] != "MetadataRef":
                    continue
                props = component["properties"]
                if props.get("type") not in {"model", "robot"}:
                    raise ValueError(f"scene_metadata_type_missing:{path}")
                identifier = int(props["path"].rsplit("/", 1)[1])
                if f"{props['type']}:{identifier}" not in cache:
                    raise ValueError(f"scene_metadata_missing:{path}:{props['path']}")
    after = tree_hash(root)
    if before != after:
        raise RuntimeError("final_models_tree_changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.joint_cache:
        joint_output.parent.mkdir(parents=True, exist_ok=True)
        joint_output.write_text(json.dumps(joints, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": not errors, "errors": sorted(set(errors)), "models": len(models["by_id"]), "robots": len(robots["by_id"]), "scenes": len(scenes),
                      "asset_tree_sha256": before, "cache": str(output)}))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

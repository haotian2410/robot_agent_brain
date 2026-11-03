"""Build Brain's derived geometry/joint files from OLS metadata only.

The current OLS contract publishes six signed AABB face coordinates in each
model/robot JSON.  This tool deliberately does not inspect OBJ vertices when
building geometry: OLS is the authority and the output stays outside the
asset tree.
"""
import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from robot_agent_brain.contracts.asset_library import geometry_from_ols_aabb


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    excluded = {".git", ".hg", ".svn"}
    for path in sorted(item for item in root.rglob("*")
                       if item.is_file() and not excluded.intersection(item.parts)):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_index(root: Path, kind: str):
    plural = "models" if kind == "model" else "robots"
    data = json.loads((root / plural / f"{kind}_index.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("by_id"), dict):
        raise ValueError(f"ols_{kind}_index_invalid")
    return {int(identifier): name for identifier, name in data["by_id"].items()}


def contained(root: Path, base: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        raise ValueError("ols_asset_path_invalid")
    path = (base / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"ols_asset_file_missing:{relative}")
    return path


def metadata_geometry(root: Path, kind: str, identifier: int, name: str):
    base = root / ("models" if kind == "model" else "robots") / str(identifier)
    metadata_path = contained(root, base, f"{name}.json")
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    semantic = data.get("semantic_properties", {})
    if semantic.get("object_id") != identifier or semantic.get("object_name") != name:
        raise ValueError(f"ols_metadata_identity_invalid:{kind}:{identifier}")
    geometry = geometry_from_ols_aabb(data.get("geometric_properties", {}).get("AABB"))
    return base, json.loads((base / f"{name}_files.json").read_text(encoding="utf-8")), geometry


def build(root: Path, manifest: dict, library_commit: str | None):
    models, robots = read_index(root, "model"), read_index(root, "robot")
    expected = {
        "model_ids": {int(value) for value in manifest["model_ids"]},
        "robot_ids": {int(value) for value in manifest["robot_ids"]},
        "scene_ids": {int(value) for value in manifest["scene_ids"]},
    }
    if set(models) != expected["model_ids"]:
        raise ValueError("ols_model_coverage_invalid")
    if set(robots) != expected["robot_ids"]:
        raise ValueError("ols_robot_coverage_invalid")
    scenes = json.loads((root / "scenes/scene_index.json").read_text(encoding="utf-8"))
    if {int(item["id"]) for item in scenes} != expected["scene_ids"]:
        raise ValueError("ols_scene_coverage_invalid")
    expected_names = manifest.get("scene_names", {})
    if any(expected_names.get(str(item["id"])) not in (None, item["name"]) for item in scenes):
        raise ValueError("ols_scene_name_mismatch")

    cache = {}
    joints = {}
    for kind, index in (("model", models), ("robot", robots)):
        for identifier, name in sorted(index.items()):
            base, files, geometry = metadata_geometry(root, kind, identifier, name)
            cache[f"{kind}:{identifier}"] = geometry.model_dump(mode="json")
            entrance = contained(root, base, files.get("path"))
            if entrance.suffix.lower() == ".urdf":
                document = ET.parse(entrance).getroot()
                joints[f"{kind}:{identifier}"] = {
                    "joints": sorted(node.attrib["name"] for node in document.findall("joint")
                                     if node.attrib.get("name")),
                    "links": sorted(node.attrib["name"] for node in document.findall("link")
                                    if node.attrib.get("name")),
                }

    for item in scenes:
        scene_path = contained(root, root / "scenes", f"{item['id']}/{item['name']}.json")
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        for obj in scene.get("objects", []):
            for component in obj.get("components", []):
                if component.get("component_type") != "MetadataRef":
                    continue
                props = component.get("properties", {})
                asset_type = props.get("type")
                path = props.get("path", "")
                if asset_type not in {"model", "robot"} or not isinstance(path, str):
                    raise ValueError(f"scene_metadata_type_missing:{scene_path}")
                try:
                    identifier = int(path.rsplit("/", 1)[1])
                except (IndexError, ValueError) as exc:
                    raise ValueError(f"scene_metadata_path_invalid:{scene_path}") from exc
                if f"{asset_type}:{identifier}" not in cache:
                    raise ValueError(f"scene_metadata_missing:{scene_path}:{path}")

    resource_version = ""
    version_path = root / "VERSION.txt"
    if version_path.is_file():
        resource_version = version_path.read_text(encoding="utf-8").splitlines()[0].strip()
    metadata = {
        "schema_version": 2,
        "source": "ols_metadata",
        "resource_version": resource_version,
        "library_commit": library_commit,
        "asset_tree_sha256": tree_hash(root),
        "aabb_format": "x+,x-,y+,y-,z+,z-",
    }
    return {"__metadata__": metadata, **cache}, joints, len(models), len(robots), len(scenes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--joint-output", required=True)
    parser.add_argument("--library-commit")
    args = parser.parse_args()
    root = Path(args.asset_root).resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    before = tree_hash(root)
    cache, joints, models, robots, scenes = build(root, manifest, args.library_commit)
    after = tree_hash(root)
    if before != after:
        raise RuntimeError("asset_tree_changed")
    output, joint_output = Path(args.output).resolve(), Path(args.joint_output).resolve()
    if output.is_relative_to(root) or joint_output.is_relative_to(root):
        raise ValueError("derived_output_inside_asset_tree")
    output.parent.mkdir(parents=True, exist_ok=True)
    joint_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    joint_output.write_text(json.dumps(joints, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"models": models, "robots": robots, "scenes": scenes,
                      "cache": str(output), "joint_inventory": str(joint_output),
                      "asset_tree_sha256": before, "asset_tree_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()

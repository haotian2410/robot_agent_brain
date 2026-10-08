"""Offline-only geometry utilities. No writes to the asset tree."""
import hashlib
import json
import math
from pathlib import Path

from robot_agent_brain.adapters.local_asset_library import read_library_index, read_asset_metadata
from robot_agent_brain.contracts.asset_library import AssetGeometry


def tree_hash(root):
    root = Path(root).resolve()
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("asset_tree_symlink_not_supported: " + str(path))
        if path.is_file():
            result.update(path.relative_to(root).as_posix().encode() + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    result.update(chunk)
            result.update(b"\0")
    return result.hexdigest()


def scan_obj(path):
    low, high, count = [math.inf] * 3, [-math.inf] * 3, 0
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            tokens = line.partition("#")[0].split()
            if not tokens or tokens[0] != "v":
                continue
            if len(tokens) not in {4, 5}:
                raise ValueError("obj_vertex_invalid")
            values = [float(item) for item in tokens[1:]]
            if not all(math.isfinite(item) for item in values) or len(values) == 4 and values[3] == 0:
                raise ValueError("obj_vertex_invalid")
            xyz = values[:3] if len(values) == 3 else [v / values[3] for v in values[:3]]
            for axis, value in enumerate(xyz):
                low[axis] = min(low[axis], value)
                high[axis] = max(high[axis], value)
            count += 1
    if count == 0:
        raise ValueError("obj_vertices_missing")
    return AssetGeometry(dimensions_m=tuple(b - a for a, b in zip(low, high)),
                         local_aabb_min_m=tuple(low), local_aabb_max_m=tuple(high))


def build_cache(root):
    root = Path(root).resolve()
    result = {}
    for identifier, name in read_library_index(root).items():
        read_asset_metadata(root, identifier, name)
        obj = (root / name / "textured.obj").resolve()
        if not obj.is_relative_to(root):
            raise ValueError("asset_obj_path_unsafe")
        result[str(identifier)] = scan_obj(obj).model_dump(mode="json")
    return result


def write_derived(root, output, data):
    output = Path(output).resolve()
    if output.is_relative_to(Path(root).resolve()):
        raise ValueError("asset_output_must_be_outside_library")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

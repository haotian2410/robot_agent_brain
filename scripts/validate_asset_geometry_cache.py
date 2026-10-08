"""Offline validation: coverage, files, bounds, and freshly measured OBJ extents."""
import argparse
import json
from pathlib import Path

from asset_geometry_tools import build_cache, tree_hash
from robot_agent_brain.contracts.asset_library import AssetGeometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--expected-count", type=int, default=21)
    args = parser.parse_args()
    before = tree_hash(args.asset_root)
    measured = build_cache(args.asset_root)
    cached = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    if set(measured) != {str(i) for i in range(1, args.expected_count + 1)} or set(cached) != set(measured):
        raise ValueError("asset_cache_coverage_invalid")
    for identifier, value in cached.items():
        if AssetGeometry.model_validate(value) != AssetGeometry.model_validate(measured[identifier]):
            raise ValueError("asset_cache_geometry_mismatch: " + identifier)
    after = tree_hash(args.asset_root)
    if before != after:
        raise RuntimeError("asset_tree_changed")
    print(json.dumps({"validated_assets": len(cached), "asset_tree_sha256_before": before,
                      "asset_tree_sha256_after": after, "asset_tree_unchanged": True}))


if __name__ == "__main__":
    main()

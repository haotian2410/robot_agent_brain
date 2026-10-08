"""Build full local OBJ bounds, without modifying the shared asset package."""
import argparse
import json

from asset_geometry_tools import build_cache, tree_hash, write_derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    before = tree_hash(args.asset_root)
    cache = build_cache(args.asset_root)
    write_derived(args.asset_root, args.output, cache)
    after = tree_hash(args.asset_root)
    if before != after:
        raise RuntimeError("asset_tree_changed")
    print(json.dumps({"assets": len(cache), "asset_tree_sha256_before": before,
                      "asset_tree_sha256_after": after, "asset_tree_unchanged": True, "output": args.output}))


if __name__ == "__main__":
    main()

"""Prepare paired OLS artifacts using the same effective config as serve."""
import argparse
from pathlib import Path
import subprocess
import sys

from robot_agent_brain.config import BrainConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--joint-inventory', required=True)
    args = parser.parse_args()
    config = BrainConfig.load(args.config)
    if not config.asset_library_root or not config.asset_geometry_cache:
        raise ValueError('OLS asset root and geometry cache must be configured')
    root = Path(config.asset_library_root).resolve()
    cache = Path(config.asset_geometry_cache).resolve()
    joints = Path(args.joint_inventory).resolve()
    if cache == joints:
        raise ValueError('Geometry cache and joint inventory must be different files')
    print(f'OLS data: {root}', flush=True)
    print(f'Geometry cache: {cache}', flush=True)
    print(f'Joint inventory: {joints}', flush=True)
    if not config.default_scene or not Path(config.default_scene).is_file():
        raise ValueError(f'Default scene missing; check config/OLS compatibility: {config.default_scene}')
    # Reuse the metadata-only builder: never derive geometry from old OBJ caches.
    subprocess.run([
        sys.executable, str(Path(__file__).with_name('build_ols_geometry_cache.py')),
        '--asset-root', str(root), '--manifest', args.manifest,
        '--output', str(cache), '--joint-output', str(joints),
    ], check=True)
    catalog = config.load_assets().catalog_snapshot()
    print(f'assets_load_ok: models={len(catalog.models)}, robots={len(catalog.robots)}', flush=True)


if __name__ == '__main__':
    main()

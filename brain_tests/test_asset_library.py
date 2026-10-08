import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from robot_agent_brain.adapters.local_asset_library import LocalAssetLibraryAdapter


CHECKOUT = Path(__file__).resolve().parents[1]


def library(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    index = {"by_name": {"apple": 1}, "by_id": {"1": "apple"}}
    (root / "object_index.json").write_text(json.dumps(index))
    folder = root / "apple"
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps({"semantic_properties": {"object_name": "apple", "object_id": 1}}))
    (folder / "textured.obj").write_text("v -0.02 -0.03 0\nv 0.05 0.06 0.1\n")
    cache = tmp_path / "cache.json"
    return root, cache


def script(name, *args):
    env = dict(os.environ)
    # Run the checkout under test, not a stale installed distribution in CI.
    env["PYTHONPATH"] = str(CHECKOUT / "src")
    return subprocess.run([sys.executable, str(CHECKOUT / "scripts" / name), *map(str, args)],
                          env=env, capture_output=True, text=True)


def test_offline_builder_validator_read_only(tmp_path):
    root, cache = library(tmp_path)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    built = script("build_asset_geometry_cache.py", "--asset-root", root, "--output", cache)
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["asset_tree_unchanged"]
    checked = script("validate_asset_geometry_cache.py", "--asset-root", root, "--cache", cache, "--expected-count", 1)
    assert checked.returncode == 0, checked.stderr
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert json.loads(cache.read_text())["1"]["local_aabb_min_m"][2] == 0


def test_runtime_only_reads_json_and_category_is_optional(tmp_path, monkeypatch):
    root, cache = library(tmp_path)
    assert script("build_asset_geometry_cache.py", "--asset-root", root, "--output", cache).returncode == 0
    original = Path.open
    def json_only(path, *args, **kwargs):
        assert path.suffix == ".json", f"runtime tried to read {path}"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", json_only)
    adapter = LocalAssetLibraryAdapter(root, cache)
    view = adapter.resolve("$LIBRARY_SERVER/1")
    assert view.library_asset_id == 1 and view.local_aabb_min_m == (-.02, -.03, 0)
    assert adapter.find_by_name("apple") == [view]
    with pytest.raises(ValueError, match="asset_category_unavailable"):
        adapter.find_by_category("fruit")


@pytest.mark.parametrize("reference", ["$LIBRARY_SERVER/<id>", "$LIBRARY_SERVER/01", "$LIBRARY_SERVER/-1", "/tmp/apple", "$LIBRARY_SERVER/1/../2"])
def test_invalid_refs_not_guessed(tmp_path, reference):
    root, cache = library(tmp_path)
    assert script("build_asset_geometry_cache.py", "--asset-root", root, "--output", cache).returncode == 0
    with pytest.raises(ValueError, match="metadata_ref_invalid"):
        LocalAssetLibraryAdapter(root, cache).resolve(reference)


def test_category_sidecar_and_scene_independent_asset_lookup(tmp_path):
    root, cache = library(tmp_path)
    script("build_asset_geometry_cache.py", "--asset-root", root, "--output", cache)
    categories = tmp_path / "categories.json"
    categories.write_text('{"1":"fruit"}')
    adapter = LocalAssetLibraryAdapter(root, cache, categories)
    assert adapter.find_by_category("fruit")[0].metadata_ref == "$LIBRARY_SERVER/1"
    assert adapter.find_by_category("container") == []
    assert adapter.resolve("$LIBRARY_SERVER/1").semantic_name == "apple"


def test_cache_cannot_be_written_into_source_tree(tmp_path):
    root, _ = library(tmp_path)
    output = root / "apple" / "metadata.json"
    before = output.read_bytes()
    result = script("build_asset_geometry_cache.py", "--asset-root", root, "--output", output)
    assert result.returncode != 0
    assert output.read_bytes() == before

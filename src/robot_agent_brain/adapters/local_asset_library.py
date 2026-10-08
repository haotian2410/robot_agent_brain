"""Read-only shared-library adapter; the only interpreter of library refs.

Runtime reads JSON only. OBJ parsing belongs to the offline cache builder.
Library semantics never overwrite the Semantic component of an existing scene.
"""
import json
from pathlib import Path
import re

from ..contracts.asset_library import AssetGeometry, BrainAssetView


def read_library_index(root):
    root = Path(root).resolve()
    index = json.loads((root / "object_index.json").read_text(encoding="utf-8"))
    if set(index) != {"by_name", "by_id"}:
        raise ValueError("asset_index_invalid")
    by_name, by_id = index["by_name"], index["by_id"]
    if not isinstance(by_name, dict) or not isinstance(by_id, dict) or not by_id:
        raise ValueError("asset_index_invalid")
    expected = {}
    normalized_names = set()
    for name, identifier in by_name.items():
        if (not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}
                or type(identifier) is not int or not 0 <= identifier <= 2**53 - 1):
            raise ValueError("asset_index_invalid")
        if str(identifier) in expected or name.casefold() in normalized_names:
            raise ValueError("asset_index_duplicate")
        directory = (root / name).resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise ValueError("asset_directory_missing_or_unsafe: " + name)
        expected[str(identifier)] = name
        normalized_names.add(name.casefold())
    if expected != by_id:
        raise ValueError("asset_index_inconsistent")
    return {int(key): value for key, value in by_id.items()}


def read_asset_metadata(root, identifier, name):
    root = Path(root).resolve()
    path = (root / name / "metadata.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("asset_metadata_path_unsafe")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    semantic = metadata.get("semantic_properties", {})
    if type(semantic.get("object_id")) is not int or semantic.get("object_id") != identifier or semantic.get("object_name") != name:
        raise ValueError("asset_metadata_identity_mismatch: " + name)
    return path, metadata


class LocalAssetLibraryAdapter:
    demo_assets = False

    def __init__(self, asset_root, geometry_cache, category_index=None, *, library_ref_prefix="$LIBRARY_SERVER/"):
        self.asset_root = Path(asset_root).resolve()
        if not library_ref_prefix or not library_ref_prefix.endswith("/"):
            raise ValueError("library_ref_prefix_invalid")
        self.library_ref_prefix = library_ref_prefix
        index = read_library_index(self.asset_root)
        cache_path = Path(geometry_cache).resolve()
        if cache_path.is_relative_to(self.asset_root):
            raise ValueError("asset_derived_file_inside_library")
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if set(cache) != {str(i) for i in index}:
            raise ValueError("asset_geometry_cache_coverage_mismatch")
        self.categories_available = category_index is not None
        categories = {}
        if category_index is not None:
            category_path = Path(category_index).resolve()
            if category_path.is_relative_to(self.asset_root):
                raise ValueError("asset_derived_file_inside_library")
            categories = json.loads(category_path.read_text(encoding="utf-8"))
            if not isinstance(categories, dict) or not set(categories) <= set(cache) or any(
                not isinstance(c, str) or not c.strip() for c in categories.values()
            ):
                raise ValueError("asset_category_index_invalid")
        self._assets = {}
        for identifier, name in index.items():
            path, _ = read_asset_metadata(self.asset_root, identifier, name)
            geometry = AssetGeometry.model_validate(cache[str(identifier)])
            self._assets[identifier] = BrainAssetView(
                library_asset_id=identifier, metadata_ref=f"{library_ref_prefix}{identifier}",
                semantic_name=name, metadata_path=str(path), category=categories.get(str(identifier)),
                **geometry.model_dump())

    def resolve(self, metadata_ref: str) -> BrainAssetView:
        if not isinstance(metadata_ref, str):
            raise ValueError("metadata_ref_invalid")
        match = re.fullmatch(re.escape(self.library_ref_prefix) + r"(0|[1-9][0-9]*)", metadata_ref)
        if match is None:
            raise ValueError("metadata_ref_invalid: " + metadata_ref)
        identifier = int(match.group(1))
        if identifier > 2**53 - 1:
            raise ValueError("metadata_ref_id_out_of_range")
        try:
            return self._assets[identifier].model_copy(deep=True)
        except KeyError as exc:
            raise LookupError("asset_missing: " + metadata_ref) from exc

    def configuration_payload(self):
        """Stable resource fingerprint input; no mesh scan or absolute paths."""
        return {
            "library_ref_prefix": self.library_ref_prefix,
            "categories_available": self.categories_available,
            "assets": [self._assets[key].model_dump(mode="json", exclude={"metadata_path"})
                       for key in sorted(self._assets)],
        }

    def find_by_name(self, semantic_name: str) -> list[BrainAssetView]:
        return [value.model_copy(deep=True) for value in self._assets.values()
                if value.semantic_name.casefold() == semantic_name.strip().casefold()]

    def find_by_category(self, category: str) -> list[BrainAssetView]:
        if not self.categories_available:
            raise ValueError("asset_category_unavailable")
        return [value.model_copy(deep=True) for value in self._assets.values()
                if value.category is not None and value.category.casefold() == category.strip().casefold()]

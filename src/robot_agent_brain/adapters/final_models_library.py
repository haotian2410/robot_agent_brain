"""Read-only adapter for the final_models models/robots namespace."""
import hashlib
import json
import re
from pathlib import Path

from ..contracts.asset_library import AssetGeometry, BrainAssetView, geometry_from_ols_aabb
from ..contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset, CatalogScene
from ..scene.colors import color_tags


class FinalModelsLibraryAdapter:
    demo_assets = False
    supports_features = True
    typed_namespaces = True

    def __init__(self, root, geometry_cache=None, category_index=None, *, library_ref_prefix="$LIBRARY_SERVER/"):
        self.root = Path(root).resolve()
        self.geometry_cache_path = str(Path(geometry_cache).resolve()) if geometry_cache else None
        self.category_index_path = str(Path(category_index).resolve()) if category_index else None
        self.prefix = library_ref_prefix
        if not self.prefix.endswith("/"):
            raise ValueError("library_ref_prefix_invalid")
        self._assets = {}
        self._scenes = []
        scene_index_path = self.root / "scenes" / "scene_index.json"
        if scene_index_path.is_file():
            scene_index = json.loads(scene_index_path.read_text(encoding="utf-8"))
            if not isinstance(scene_index, list):
                raise ValueError("scene_index_invalid")
            for item in scene_index:
                if (not isinstance(item, dict) or type(item.get("id")) is not int
                        or not isinstance(item.get("name"), str) or not item["name"]):
                    raise ValueError("scene_index_invalid")
                self._scenes.append(CatalogScene(
                    scene_key=f"scene:{item['id']}", name=item["name"],
                    display_name=item.get("display_name") or item["name"]))
        cache, cache_metadata = self._load_geometry_cache(geometry_cache)
        self._validate_cache_metadata(cache_metadata, geometry_cache)
        self.geometry_cache_metadata = cache_metadata
        categories = json.loads(Path(category_index).read_text(encoding="utf-8")) if category_index else {}
        self.categories_available = category_index is not None
        self._passive_mechanism_keys = set()
        for kind in ("model", "robot"):
            index = json.loads((self.root / ("models" if kind == "model" else "robots") /
                                ("model_index.json" if kind == "model" else "robot_index.json")).read_text(encoding="utf-8"))
            index_categories = index.get("category", {})
            for identifier, name in index["by_id"].items():
                identifier = int(identifier)
                directory = self.root / ("models" if kind == "model" else "robots") / str(identifier)
                metadata = directory / f"{name}.json"
                data = json.loads(metadata.read_text(encoding="utf-8"))
                semantic = data["semantic_properties"]
                if type(semantic.get("object_id")) is not int or semantic["object_id"] != identifier:
                    raise ValueError(f"asset_metadata_identity_mismatch: {kind}/{identifier}")
                if semantic.get("object_name") != name:
                    raise ValueError(f"asset_metadata_name_mismatch: {kind}/{identifier}")
                key = f"{kind}:{identifier}"
                metadata_geometry = None
                raw_aabb = data.get("geometric_properties", {}).get("AABB")
                if isinstance(raw_aabb, list) and len(raw_aabb) == 6:
                    metadata_geometry = geometry_from_ols_aabb(raw_aabb)
                if metadata_geometry is not None:
                    # The OLS document is authoritative.  A supplied cache is
                    # only a derived validation artifact; refusing stale data
                    # prevents an old asset package from silently supplying
                    # bounds for a newer one.
                    if key in cache and AssetGeometry.model_validate(cache[key]) != metadata_geometry:
                        raise ValueError(f"asset_geometry_cache_mismatch:{key}")
                    geometry = metadata_geometry
                else:
                    if key not in cache:
                        raise ValueError(f"asset_geometry_missing:{key}")
                    geometry = AssetGeometry.model_validate(cache[key])
                tags = tuple(tag.strip().casefold() for tag in semantic.get("tag", "").split(",") if tag.strip())
                # Models with an embedded RobotDriver are passive articulated
                # mechanisms (drawer/cabinet/microwave/button/table), not
                # ordinary scene-add assets.  Keep them in the complete
                # catalog for query/capability-boundary reasoning, but mark
                # them unavailable for a live scene_edit.add/replace choice.
                passive_mechanism = kind == "model" and "robot_driver" in data
                if passive_mechanism:
                    self._passive_mechanism_keys.add(key)
                view = BrainAssetView(
                    **geometry.model_dump(), library_asset_id=identifier,
                    metadata_ref=f"{self.prefix}{identifier}", semantic_name=name,
                    metadata_path=str(metadata), asset_type=kind,
                    tags=tags, color_tags=color_tags(tags), scalable=semantic.get("scalable"),
                    scale_range=data.get("physical_properties", {}).get("scale"),
                    category=(categories.get(key) or categories.get(str(identifier))
                              or index_categories.get(str(identifier))),
                    physical_properties=data.get("physical_properties", {}),
                    grasp_properties=data.get("grasp_properties", {}),
                )
                self._assets[key] = view

    def refresh_from_source(self) -> bool:
        """Atomically reload the read-only OLS index and metadata.

        OLS is allowed to publish a new catalog while Brain stays up.  The
        previous implementation only re-hashed the adapter's in-memory maps,
        so a newly added model could never reach the next turn.  Build a new
        adapter first; only replace this instance after every identity,
        geometry-cache and metadata check succeeds.
        """
        aliases = getattr(self, "catalog_aliases", {})
        fresh = type(self)(self.root, self.geometry_cache_path,
                           self.category_index_path, library_ref_prefix=self.prefix)
        fresh.catalog_aliases = dict(aliases)
        before = self.catalog_snapshot(aliases=aliases).revision
        after = fresh.catalog_snapshot(aliases=aliases).revision
        if before == after:
            return False
        self.__dict__.clear()
        self.__dict__.update(fresh.__dict__)
        self.catalog_aliases = dict(aliases)
        return True

    @staticmethod
    def _load_geometry_cache(path):
        if path is None:
            return {}, {}
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("asset_geometry_cache_invalid")
        metadata = raw.get("__metadata__", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("asset_geometry_cache_metadata_invalid")
        return {key: value for key, value in raw.items() if key != "__metadata__"}, metadata

    def _validate_cache_metadata(self, metadata, path):
        """Reject a derived cache from another OLS package.

        Small in-memory fixtures intentionally omit the metadata block.  Real
        OLS roots publish VERSION.txt and must use the metadata-only cache
        generated by ``build_ols_geometry_cache.py``; otherwise a stale old
        package could silently provide dimensions for a new one.
        """
        version_path = self.root / "VERSION.txt"
        if not version_path.is_file():
            return
        # OLS metadata is authoritative and is sufficient on its own.  A
        # cache is optional; when present it is checked as a derived artifact.
        if path is None:
            return
        required = {"schema_version", "source", "resource_version", "asset_tree_sha256", "aabb_format"}
        if not required <= set(metadata):
            raise ValueError("asset_geometry_cache_metadata_invalid")
        if metadata.get("source") != "ols_metadata" or metadata.get("aabb_format") != "x+,x-,y+,y-,z+,z-":
            raise ValueError("asset_geometry_cache_source_invalid")
        resource_version = version_path.read_text(encoding="utf-8").splitlines()[0].strip()
        if metadata.get("resource_version") != resource_version:
            raise ValueError("asset_geometry_cache_version_mismatch")
        digest = hashlib.sha256()
        excluded = {".git", ".hg", ".svn"}
        for item in sorted(path for path in self.root.rglob("*")
                           if path.is_file() and not excluded.intersection(path.parts)):
            relative = item.relative_to(self.root).as_posix().encode("utf-8")
            digest.update(relative + b"\0")
            digest.update(item.read_bytes())
            digest.update(b"\0")
        if metadata.get("asset_tree_sha256") != digest.hexdigest():
            raise ValueError("asset_geometry_cache_tree_mismatch")

    def resolve(self, metadata_ref, asset_type=None):
        match = re.fullmatch(re.escape(self.prefix) + r"(0|[1-9][0-9]*)", metadata_ref or "")
        if match is None:
            raise ValueError("metadata_ref_invalid: " + str(metadata_ref))
        identifier = int(match.group(1))
        matches = [view for key, view in self._assets.items() if view.library_asset_id == identifier]
        if asset_type is not None:
            matches = [view for view in matches if view.asset_type == asset_type]
        if len(matches) != 1:
            raise ValueError("metadata_ref_type_required_or_unknown: " + str(metadata_ref))
        return matches[0].model_copy(deep=True)

    def find_by_name(self, semantic_name):
        name = semantic_name.strip().casefold()
        return [view.model_copy(deep=True) for view in self._assets.values() if view.semantic_name.casefold() == name]

    def find_by_category(self, category):
        if not self.categories_available:
            raise ValueError("asset_category_unavailable")
        value = category.strip().casefold()
        return [view.model_copy(deep=True) for view in self._assets.values()
                if view.category and view.category.casefold() == value]

    def find_by_tag(self, tag, *, asset_type="model"):
        value = tag.strip().casefold()
        return [view.model_copy(deep=True) for view in self._assets.values()
                if view.asset_type == asset_type and value in view.tags]

    def configuration_payload(self):
        return {"library_ref_prefix": self.prefix, "assets": [
            view.model_dump(mode="json", exclude={"metadata_path", "physical_properties", "grasp_properties"})
            for view in sorted(self._assets.values(), key=lambda item: (item.asset_type, item.library_asset_id))],
                "geometry_cache_metadata": self.geometry_cache_metadata}

    def catalog_snapshot(self, *, aliases=None, registered_profiles=None) -> AssetCatalogSnapshot:
        """Expose the complete read-only OLS directory without private state access."""
        alias_map = {str(k).casefold(): str(v).casefold() for k, v in (aliases or {}).items()}
        models, robots = [], []
        canonical_names = {view.semantic_name.casefold() for view in self._assets.values()}
        for view in sorted(self._assets.values(), key=lambda item: (item.asset_type, item.library_asset_id)):
            aliases_for_name = tuple(sorted({key for key, value in alias_map.items()
                                               if value == view.semantic_name.casefold() and key not in canonical_names}))
            passive_mechanism = f"{view.asset_type}:{view.library_asset_id}" in self._passive_mechanism_keys
            item = CatalogAsset(
                asset_key=f"{view.asset_type}:{view.library_asset_id}", name=view.semantic_name,
                display_name=view.semantic_name, aliases=aliases_for_name,
                tags=tuple(view.tags), category=view.category, asset_type=view.asset_type,
                metadata_ref=view.metadata_ref,
                selectable_for_add=(view.asset_type == "model" and not passive_mechanism),
                availability_reason=("passive_mechanism_only" if passive_mechanism
                                     else (None if view.asset_type == "model" else "robot_platform_only")),
                scalable=view.scalable, scale_range=view.scale_range)
            (models if view.asset_type == "model" else robots).append(item)
        return AssetCatalogSnapshot.from_items(models, robots, scenes=self._scenes,
                                               registered_profiles=registered_profiles or ())

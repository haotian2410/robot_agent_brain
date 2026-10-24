"""Read-only adapter for the final_models models/robots namespace."""
import json
import re
from pathlib import Path

from ..contracts.asset_library import AssetGeometry, BrainAssetView
from ..scene.colors import color_tags


class FinalModelsLibraryAdapter:
    demo_assets = False
    supports_features = True
    typed_namespaces = True

    def __init__(self, root, geometry_cache, category_index=None, *, library_ref_prefix="$LIBRARY_SERVER/"):
        self.root = Path(root).resolve()
        self.prefix = library_ref_prefix
        if not self.prefix.endswith("/"):
            raise ValueError("library_ref_prefix_invalid")
        self._assets = {}
        cache = json.loads(Path(geometry_cache).read_text(encoding="utf-8"))
        categories = json.loads(Path(category_index).read_text(encoding="utf-8")) if category_index else {}
        self.categories_available = category_index is not None
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
                geometry = AssetGeometry.model_validate(cache[key])
                tags = tuple(tag.strip().casefold() for tag in semantic.get("tag", "").split(",") if tag.strip())
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
            for view in sorted(self._assets.values(), key=lambda item: (item.asset_type, item.library_asset_id))]}

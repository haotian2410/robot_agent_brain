"""Explicit metadata-only demo resources using the same AssetLibraryPort."""
from ..contracts.asset_library import BrainAssetView
from ..contracts.asset_catalog import AssetCatalogSnapshot, CatalogAsset
from .local_asset_catalog import AssetDocument


class DemoAssetLibrary:
    demo_assets = True

    def __init__(self, document):
        self.metadata = AssetDocument.model_validate(document)
        if not self.metadata.demo_assets:
            raise ValueError("demo_asset_document_required")
        if set(self.metadata.library_ids) != {model.asset_id for model in self.metadata.models}:
            raise ValueError("demo_library_id_coverage_invalid")
        self._views = {}
        for model in self.metadata.models:
            if model.aabb_m is None:
                raise ValueError("demo_asset_explicit_bounds_required: " + model.asset_id)
            identifier = self.metadata.library_ids[model.asset_id]
            ref = f"$DEMO_LIBRARY/{identifier}"
            self._views[ref] = BrainAssetView(library_asset_id=identifier, metadata_ref=ref,
                semantic_name=model.semantic_name, category=model.category,
                dimensions_m=model.dimensions_m, local_aabb_min_m=model.aabb_m[:3],
                local_aabb_max_m=model.aabb_m[3:])

    def resolve(self, metadata_ref, asset_type=None):
        try:
            return self._views[metadata_ref].model_copy(deep=True)
        except (KeyError, TypeError) as exc:
            raise LookupError("asset_missing: " + str(metadata_ref)) from exc

    def find_by_name(self, name):
        return [model.model_copy(deep=True) for model in self._views.values()
                if model.semantic_name.casefold() == name.strip().casefold()]

    def find_by_category(self, category):
        return [model.model_copy(deep=True) for model in self._views.values()
                if model.category.casefold() == category.strip().casefold()]

    def configuration_payload(self):
        return self.metadata.model_dump(mode="json")

    def catalog_snapshot(self, *, aliases=None, registered_profiles=None) -> AssetCatalogSnapshot:
        configured_aliases = getattr(self, "catalog_aliases", {}) if aliases is None else aliases
        alias_map = {str(k).casefold(): str(v).casefold() for k, v in (configured_aliases or {}).items()}
        models = []
        canonical_names = {view.semantic_name.casefold() for view in self._views.values()}
        for view in sorted(self._views.values(), key=lambda item: item.library_asset_id):
            models.append(CatalogAsset(
                asset_key=f"model:{view.library_asset_id}", name=view.semantic_name,
                display_name=view.semantic_name,
                aliases=tuple(sorted({key for key, value in alias_map.items()
                                      if value == view.semantic_name.casefold() and key not in canonical_names})),
                category=view.category, asset_type="model", metadata_ref=view.metadata_ref,
                selectable_for_add=True))
        return AssetCatalogSnapshot.from_items(models, [], registered_profiles=registered_profiles or ())

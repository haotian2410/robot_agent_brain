"""Semantic resource selection through the AssetLibraryPort only."""
from dataclasses import dataclass
from ..contracts.asset_library import BrainAssetView


@dataclass
class AssetBinding:
    model: BrainAssetView
    assumptions: list[str]


class AssetResolver:
    def __init__(self, catalog, *, aliases=None, category_aliases=None):
        self.catalog = catalog
        self.aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (aliases or {}).items()}
        self.category_aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (category_aliases or {}).items()}

    def resolve(self, entity, *, infer_category=False):
        name = entity.semantic_name.strip().casefold()
        name = self.aliases.get(name, name)
        category = entity.category.strip().casefold()
        category = self.category_aliases.get(category, category)
        if entity.color:
            raise ValueError("asset_color_evidence_missing: " + entity.color)
        candidates = (self.catalog.find_by_category(category) if entity.category_only
                      else self.catalog.find_by_name(name))
        if not candidates:
            raise ValueError("asset_missing: " + entity.semantic_name)
        # Categories are optional resource selection hints, not a requirement
        # for named resource resolution or existing Scene Semantic facts.
        if not infer_category:
            candidates = [model for model in candidates if model.category is None or model.category.casefold() == category]
            if not candidates:
                raise ValueError("asset_category_mismatch: " + entity.category)
        if len(candidates) != 1:
            raise ValueError("asset_ambiguous: " + entity.semantic_name)
        assumptions = ["demo_assets: metadata only; no real mesh or rendered material"] if getattr(self.catalog, "demo_assets", False) else []
        return AssetBinding(candidates[0], assumptions)

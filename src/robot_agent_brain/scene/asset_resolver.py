"""Semantic resource selection through the AssetLibraryPort only."""
from dataclasses import dataclass
from ..contracts.asset_library import BrainAssetView
from .asset_features import matches_features


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
        if getattr(self.catalog, "typed_namespaces", False) and category == "furniture_component":
            category = "furniture"
        if (entity.color or entity.tags) and not getattr(self.catalog, "supports_features", False):
            raise ValueError("asset_color_evidence_missing: " + entity.color)
        candidates = (self.catalog.find_by_category(category) if entity.category_only
                      else self.catalog.find_by_name(name))
        if not candidates:
            raise ValueError("asset_missing: " + entity.semantic_name)
        if entity.color or entity.tags:
            candidates = [model for model in candidates if matches_features(model, entity)]
            if not candidates:
                raise ValueError("asset_feature_missing: " + entity.semantic_name)
        # Categories are optional resource selection hints, not a requirement
        # for named resource resolution or existing Scene Semantic facts.
        # Typed Scene v1 uses lexical categories that need not match the model's
        # wording (baseball: ball vs sports_equipment). As in existing-scene
        # grounding, an explicit exact resource name is stronger evidence.
        # Category-only requests and legacy catalog constraints remain strict.
        named_typed = getattr(self.catalog, "typed_namespaces", False) and not entity.category_only
        if not infer_category and not named_typed:
            candidates = [model for model in candidates if model.category is None or model.category.casefold() == category]
            if not candidates:
                raise ValueError("asset_category_mismatch: " + entity.category)
        if len(candidates) != 1:
            raise ValueError("asset_ambiguous: " + entity.semantic_name + "; 请补充颜色或款式: " +
                             ", ".join(f"{m.asset_type}:{m.library_asset_id} ({' '.join(m.tags)})" for m in candidates))
        assumptions = ["demo_assets: metadata only; no real mesh or rendered material"] if getattr(self.catalog, "demo_assets", False) else []
        return AssetBinding(candidates[0], assumptions)

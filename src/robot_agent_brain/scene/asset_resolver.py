"""Semantic resource selection through the AssetLibraryPort only."""
from dataclasses import dataclass
from ..contracts.asset_library import BrainAssetView
from .asset_features import matches_features


@dataclass
class AssetBinding:
    model: BrainAssetView
    assumptions: list[str]


class AssetResolver:
    def __init__(self, catalog, *, aliases=None, category_aliases=None, default_refs=None):
        self.catalog = catalog
        self.aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (aliases or {}).items()}
        self.category_aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (category_aliases or {}).items()}
        self.default_refs = {k.strip().casefold(): v for k, v in (default_refs or {}).items()}

    def resolve(self, entity, *, infer_category=False, allow_default=False):
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
            # Defaults are intentionally limited to scene additions without
            # explicit style evidence. Existing-object selection and robot
            # planning continue to require an unambiguous match.
            if (allow_default and not entity.color and not entity.tags and not entity.category_only
                    and name in self.default_refs):
                ref = self.default_refs[name]
                try:
                    default_model = self.catalog.resolve(ref, asset_type="model")
                except (AttributeError, ValueError) as exc:
                    raise ValueError("default_asset_invalid: " + name) from exc
                alternatives = [f"{m.asset_type}:{m.library_asset_id} ({', '.join(m.tags)})" for m in candidates
                                if m.metadata_ref != default_model.metadata_ref]
                assumptions = [f"source=default_asset: {name} -> {default_model.asset_type}:{default_model.library_asset_id}"]
                if alternatives:
                    assumptions.append("alternatives=" + ",".join(alternatives))
                if getattr(self.catalog, "demo_assets", False):
                    assumptions.append("demo_assets: metadata only; no real mesh or rendered material")
                return AssetBinding(default_model, assumptions)
            raise ValueError("asset_ambiguous: " + entity.semantic_name + "; 请补充颜色或款式: " +
                             ", ".join(f"{m.asset_type}:{m.library_asset_id} ({' '.join(m.tags)})" for m in candidates))
        assumptions = ["demo_assets: metadata only; no real mesh or rendered material"] if getattr(self.catalog, "demo_assets", False) else []
        return AssetBinding(candidates[0], assumptions)

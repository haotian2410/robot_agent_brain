"""Semantic resource selection through the AssetLibraryPort only."""
from dataclasses import dataclass
from ..contracts.asset_library import BrainAssetView
from .asset_features import matches_features, tag_overlap_score
from .colors import ColorResolver


@dataclass
class AssetBinding:
    model: BrainAssetView
    assumptions: list[str]
    color_override: str | None = None


class AssetResolver:
    def __init__(self, catalog, *, aliases=None, category_aliases=None, default_refs=None):
        self.catalog = catalog
        self.aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (aliases or {}).items()}
        self.category_aliases = {k.strip().casefold(): v.strip().casefold() for k, v in (category_aliases or {}).items()}
        self.default_refs = {k.strip().casefold(): v for k, v in (default_refs or {}).items()}

    def _resolve_asset_key(self, asset_key: str):
        """Resolve the exact model selected by the v3 catalog snapshot."""
        if not isinstance(asset_key, str) or not asset_key.startswith("model:"):
            raise ValueError("asset_catalog_key_invalid: " + str(asset_key))
        snapshot = self.catalog.catalog_snapshot(aliases={}) if hasattr(self.catalog, "catalog_snapshot") else None
        item = next((row for row in (snapshot.models if snapshot is not None else ())
                     if row.asset_key == asset_key), None)
        if item is None:
            raise ValueError("asset_catalog_key_invalid: " + str(asset_key))
        try:
            return self.catalog.resolve(item.metadata_ref, asset_type="model")
        except (LookupError, ValueError) as exc:
            raise ValueError("asset_catalog_key_unresolvable: " + asset_key) from exc

    def resolve(self, entity, *, infer_category=False, allow_default=False, allow_color_override=False,
                asset_key=None):
        if asset_key is not None:
            model = self._resolve_asset_key(asset_key)
            if entity.color and not entity.tags:
                return AssetBinding(model, [f"source=asset_catalog: {asset_key}"], ColorResolver.resolve(entity.color))
            # When asset_key is explicitly provided by Qwen, trust the selection.
            # Only validate that at least some tags overlap (lenient check).
            if entity.tags:
                overlap = tag_overlap_score(model, entity.tags)
                if overlap == 0:
                    raise ValueError("asset_feature_missing: " + entity.semantic_name)
            return AssetBinding(model, [f"source=asset_catalog: {asset_key}"])

        category = entity.category.strip().casefold()
        category = self.category_aliases.get(category, category)
        if getattr(self.catalog, "typed_namespaces", False) and category == "furniture_component":
            category = "furniture"

        # Primary path: tag overlap matching when entity has tags
        if entity.tags:
            return self._resolve_by_tag_overlap(entity, category, infer_category, allow_default, allow_color_override)

        # Fallback: semantic_name matching (backward compatibility)
        return self._resolve_by_name(entity, category, infer_category, allow_default, allow_color_override)

    def _resolve_by_tag_overlap(self, entity, category, infer_category, allow_default, allow_color_override):
        """Resolve asset by computing tag overlap scores."""
        if hasattr(self.catalog, "find_by_tag_overlap"):
            scored = self.catalog.find_by_tag_overlap(entity.tags)
        else:
            scored = []
            all_models = [v for v in self.catalog._assets.values() if not v.no_display and v.asset_type == "model"]
            for view in all_models:
                score = tag_overlap_score(view, entity.tags)
                if score > 0:
                    scored.append((view, score))
            scored.sort(key=lambda p: p[1], reverse=True)

        if not scored:
            raise ValueError("asset_tag_no_match: " + ", ".join(entity.tags))

        max_score = scored[0][1]
        top_candidates = [(v, s) for v, s in scored if s == max_score]
        tied = len(top_candidates)
        # Which stage collapsed the tie, so a report can say why this model and
        # not its equally-scored siblings won.
        via = "none"

        # Tiebreaker 1: semantic_name match
        if tied > 1 and entity.semantic_name:
            name = entity.semantic_name.strip().casefold()
            name = self.aliases.get(name, name)
            name_matches = [(v, s) for v, s in top_candidates if v.semantic_name.casefold() == name]
            if 0 < len(name_matches) < len(top_candidates):
                top_candidates = name_matches
                via = "name"

        # Tiebreaker 2: default_scene_edit_assets - check if any candidate's semantic_name is in defaults
        if len(top_candidates) > 1 and allow_default:
            # First try entity.semantic_name
            if entity.semantic_name:
                name = entity.semantic_name.strip().casefold()
                if name in self.default_refs:
                    default_model = self.catalog.resolve(self.default_refs[name], asset_type="model")
                    default_match = [(v, s) for v, s in top_candidates if v.library_asset_id == default_model.library_asset_id]
                    if 0 < len(default_match) < len(top_candidates):
                        top_candidates = default_match
                        via = "default"
            # Then try matching any candidate's semantic_name against default_refs keys
            if len(top_candidates) > 1:
                for v, s in top_candidates:
                    if v.semantic_name.casefold() in self.default_refs:
                        default_model = self.catalog.resolve(self.default_refs[v.semantic_name.casefold()], asset_type="model")
                        if default_model.library_asset_id == v.library_asset_id:
                            top_candidates = [(v, s)]
                            via = "default"
                            break

        if len(top_candidates) != 1:
            # Category filter if not inferring
            if not infer_category and not getattr(self.catalog, "typed_namespaces", False):
                filtered = [(v, s) for v, s in top_candidates if v.category is None or v.category.casefold() == category]
                if 0 < len(filtered) < len(top_candidates):
                    top_candidates = filtered
                    via = "category"

        if len(top_candidates) != 1:
            alternatives = [f"{v.asset_type}:{v.library_asset_id} (score={s}, tags={v.tags})" for v, s in top_candidates[:5]]
            raise ValueError("asset_ambiguous_by_tags: " + ", ".join(entity.tags) + "; candidates: " + ", ".join(alternatives))

        model, score = top_candidates[0]
        assumptions = [f"source=tag_overlap: score={score}, tags={','.join(entity.tags)}"]
        if via != "none":
            assumptions.append(f"tiebreak={via}: {tied} tied candidates -> "
                               f"{model.asset_type}:{model.library_asset_id}")
        if getattr(self.catalog, "demo_assets", False):
            assumptions.append("demo_assets: metadata only; no real mesh or rendered material")

        color_override = None
        if entity.color and allow_color_override:
            color_override = ColorResolver.resolve(entity.color)

        return AssetBinding(model, assumptions, color_override)

    def _resolve_by_name(self, entity, category, infer_category, allow_default, allow_color_override):
        """Resolve asset by semantic_name (legacy path)."""
        name = entity.semantic_name.strip().casefold()
        name = self.aliases.get(name, name)

        if ((entity.color or entity.tags)
                and not getattr(self.catalog, "supports_features", False)
                and not (allow_color_override and entity.color and not entity.tags)):
            raise ValueError("asset_color_evidence_missing: " + str(entity.color))
        candidates = (self.catalog.find_by_category(category) if entity.category_only
                      else self.catalog.find_by_name(name))
        if not candidates:
            raise ValueError("asset_missing: " + entity.semantic_name)
        color_override = None
        if entity.color or entity.tags:
            unfiltered = list(candidates)
            candidates = [model for model in candidates if matches_features(model, entity)]
            if not candidates:
                if allow_color_override and entity.color and not entity.tags:
                    if len(unfiltered) == 1:
                        candidates = unfiltered
                    elif allow_default and name in self.default_refs:
                        default_model = self.catalog.resolve(self.default_refs[name], asset_type="model")
                        candidates = [default_model]
                    else:
                        raise ValueError("asset_feature_missing: " + entity.semantic_name)
                    color_override = ColorResolver.resolve(entity.color)
                else:
                    raise ValueError("asset_feature_missing: " + entity.semantic_name)
        named_typed = getattr(self.catalog, "typed_namespaces", False) and not entity.category_only
        if not infer_category and not named_typed:
            candidates = [model for model in candidates if model.category is None or model.category.casefold() == category]
            if not candidates:
                raise ValueError("asset_category_mismatch: " + entity.category)
        if len(candidates) != 1:
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
                return AssetBinding(default_model, assumptions, color_override)
            raise ValueError("asset_ambiguous: " + entity.semantic_name + "; 请补充颜色或款式: " +
                             ", ".join(f"{m.asset_type}:{m.library_asset_id} ({' '.join(m.tags)})" for m in candidates))
        assumptions = ["demo_assets: metadata only; no real mesh or rendered material"] if getattr(self.catalog, "demo_assets", False) else []
        return AssetBinding(candidates[0], assumptions, color_override)

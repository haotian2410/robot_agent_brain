from dataclasses import dataclass
from ..contracts.scene import ModelProperty


@dataclass
class AssetBinding:
    model: ModelProperty
    properties: dict
    assumptions: list[str]


class AssetResolver:
    def __init__(self, catalog):
        self.catalog = catalog

    def resolve(self, entity, *, infer_category=False):
        metadata = self.catalog.metadata
        name = entity.semantic_name.strip().casefold()
        category = entity.category.strip().casefold()
        names = {m.semantic_name.casefold() for m in metadata.models}
        aliases = {k.strip().casefold(): v.strip().casefold() for k, v in metadata.aliases.items()}
        category_aliases = {k.strip().casefold(): v.strip().casefold() for k, v in metadata.category_aliases.items()}
        if name not in names:
            name = aliases.get(name, name)
        category = category_aliases.get(category, category)
        candidates = [m for m in metadata.models if
                      (m.category.casefold() == category if entity.category_only else m.semantic_name.casefold() == name)]
        if not candidates:
            raise ValueError("asset_missing: " + entity.semantic_name)
        if not infer_category:
            candidates = [m for m in candidates if m.category.casefold() == category]
            if not candidates:
                raise ValueError("asset_category_mismatch: " + entity.category)
        if entity.color:
            candidates = [m for m in candidates
                          if metadata.intrinsic_properties.get(m.asset_id, {}).get("color") == entity.color
                          or "color" in metadata.overridable_properties.get(m.asset_id, [])]
            if not candidates:
                raise ValueError("asset_color_unsupported: " + entity.color)
        if len(candidates) != 1:
            raise ValueError("asset_ambiguous: " + entity.semantic_name)
        model = candidates[0].model_copy(deep=True)
        properties = dict(metadata.intrinsic_properties.get(model.asset_id, {}))
        if entity.color:
            properties["color"] = entity.color
        assumptions = ["demo_assets: metadata only; no real mesh or rendered material"] if metadata.demo_assets else []
        return AssetBinding(model, properties, assumptions)

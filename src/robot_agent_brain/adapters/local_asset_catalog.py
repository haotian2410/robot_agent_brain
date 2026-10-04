from ..contracts.scene import ModelProperty


class LocalAssetCatalog:
    def __init__(self, models: list[ModelProperty] | None = None):
        self._models = {item.asset_id: item for item in (models or [])}

    def add(self, model: ModelProperty) -> None:
        self._models[model.asset_id] = model

    def find_models(self, semantic_name: str, category: str) -> list[ModelProperty]:
        return [m.model_copy(deep=True) for m in self._models.values()
                if m.semantic_name.casefold() == semantic_name.casefold()
                and m.category.casefold() == category.casefold()]

    def get_model_property(self, asset_id: str) -> ModelProperty:
        try:
            return self._models[asset_id]
        except KeyError as exc:
            raise LookupError(f"asset_model_property_missing: {asset_id}") from exc

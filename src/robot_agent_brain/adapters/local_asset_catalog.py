from ..contracts.scene import ModelProperty


class LocalAssetCatalog:
    def __init__(self, models: list[ModelProperty] | None = None):
        self._models = {item.asset_id: item for item in (models or [])}

    def add(self, model: ModelProperty) -> None:
        self._models[model.asset_id] = model

    def get_model_property(self, asset_id: str) -> ModelProperty:
        try:
            return self._models[asset_id]
        except KeyError as exc:
            raise LookupError(f"asset_model_property_missing: {asset_id}") from exc


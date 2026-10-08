from typing import Protocol
from ..contracts.model_property import ModelProperty


class AssetCatalogPort(Protocol):
    def get_model_property(self, asset_id: str) -> ModelProperty: ...
    def find_models(self, semantic_name: str, category: str) -> list[ModelProperty]: ...

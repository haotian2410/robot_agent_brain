from typing import Protocol
from ..contracts.scene import ModelProperty


class AssetCatalogPort(Protocol):
    def get_model_property(self, asset_id: str) -> ModelProperty: ...


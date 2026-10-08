from robot_agent_brain.adapters.local_asset_catalog import LocalAssetCatalog
from robot_agent_brain.contracts.model_property import ModelProperty


def apple_assets() -> LocalAssetCatalog:
    return LocalAssetCatalog([
        ModelProperty(asset_id="apple_basic", semantic_name="apple", category="fruit", dimensions_m=(0.08, 0.08, 0.09)),
        ModelProperty(asset_id="baseball_basic", semantic_name="baseball", category="ball", dimensions_m=(0.074, 0.074, 0.074)),
        ModelProperty(asset_id="box_basic", semantic_name="box", category="container", dimensions_m=(0.30, 0.25, 0.12)),
    ])

"""Explicit new-protocol test helpers, never legacy runtime conversion."""
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.scene.bootstrapper import SceneBootstrapper
from robot_agent_brain.scene.component_access import SceneIndex


def demo_bootstrap(config=None):
    config = config or BrainConfig()
    assets = config.load_assets()
    settings = config.bootstrap_settings()
    return assets, SceneBootstrapper(assets, config.load_defaults(),
        table_metadata_ref=settings["default_table_metadata_ref"],
        robot_metadata_ref=settings["default_robot_metadata_ref"],
        robot_driver=settings["default_robot_driver"], aliases=assets.metadata.aliases,
        category_aliases=assets.metadata.category_aliases)


def semantic_names(scene):
    index = SceneIndex(scene)
    return [index.semantic(obj.object_id_in_scene).semantic_name for obj in index.semantic_objects()]


def named_objects(scene, name):
    index = SceneIndex(scene)
    return [obj for obj in index.semantic_objects() if index.semantic(obj.object_id_in_scene).semantic_name == name]

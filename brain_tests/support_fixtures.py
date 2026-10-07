"""Explicit support geometry for editor fixtures (not production defaults)."""
from robot_agent_brain.contracts.scene import ModelProperty, SceneObject, Transform


def add_table(scene, assets):
    first = scene.objects[0]
    top = first.transform.position[2] - assets.get_model_property(first.asset_id).dimensions_m[2] / 2
    assets.add(ModelProperty(asset_id="fixture_table", semantic_name="table", category="surface", dimensions_m=(2, 2, .05)))
    assets.metadata.center_origin_assets = [m.asset_id for m in assets.metadata.models]
    scene.objects.append(SceneObject(scene_object_id="table_01", asset_id="fixture_table", semantic_name="table",
        category="surface", transform=Transform(position=(0, 0, top-.025))))
    return scene

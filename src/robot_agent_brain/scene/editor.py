from __future__ import annotations

from ..contracts.scene import PatchAction, SceneObject, ScenePatch, ScenePatchOperation, Transform
from ..contracts.task_intent import PlacementTarget
from ..ports.asset_catalog import AssetCatalogPort
from .scene_layout import SceneLayoutPolicy


class SceneEditor:
    """Create semantic scene-layout patches; it never creates robot poses."""

    def __init__(self, assets: AssetCatalogPort, layout: SceneLayoutPolicy | None = None):
        self.assets = assets
        self.layout = layout or SceneLayoutPolicy()

    def add_object(
        self,
        scene,
        scene_object_id: str,
        asset_id: str,
        semantic_name: str,
        category: str,
        *,
        relation: PlacementTarget | None = None,
        reference_object: SceneObject | None = None,
    ) -> ScenePatch:
        model = self.assets.get_model_property(asset_id)
        transform = Transform()
        if relation is not None and relation.reference is not None:
            if reference_object is None:
                raise ValueError("scene_edit_reference_missing")
            reference_model = self.assets.get_model_property(reference_object.asset_id)
            transform = self.layout.relative_transform(
                relation.relation or "right_of",
                reference_object.transform,
                reference_model,
                model,
            )
        object_value = SceneObject(
            scene_object_id=scene_object_id,
            asset_id=asset_id,
            semantic_name=semantic_name,
            category=category,
            transform=transform,
        )
        return ScenePatch(
            scene_id=scene.scene_id,
            base_scene_version=scene.scene_version,
            operations=[ScenePatchOperation(action=PatchAction.ADD, scene_object_id=scene_object_id, object=object_value)],
        )


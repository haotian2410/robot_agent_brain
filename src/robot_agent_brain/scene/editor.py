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

    def edit(self, intent, scene) -> ScenePatch:
        """Resolve names to assets/instances before producing a versioned patch."""
        reference = None
        if intent.reference:
            refs = [o for o in scene.objects if o.scene_object_id == intent.reference]
            if not refs:
                refs = [o for o in scene.objects if o.semantic_name.casefold() == intent.reference.casefold()]
            if len(refs) != 1:
                raise ValueError("scene_edit_reference_missing" if not refs else "scene_edit_reference_ambiguous")
            reference = refs[0]
        if intent.operation == "add":
            models = self.assets.find_models(intent.semantic_name, intent.category)
            if len(models) != 1:
                raise ValueError("scene_edit_asset_missing" if not models else "scene_edit_asset_ambiguous")
            if reference is None:
                raise ValueError("scene_edit_reference_missing: specify the initial placement reference")
            model = models[0]
            used = {o.scene_object_id for o in scene.objects}
            operations = []
            for _ in range(intent.count):
                index = 1
                while f"{intent.semantic_name}_{index:02d}" in used or f"{intent.semantic_name}_{index:02d}" in scene.retired_object_ids:
                    index += 1
                object_id = f"{intent.semantic_name}_{index:02d}"
                used.add(object_id)
                patch = self.add_object(
                    scene, object_id, model.asset_id, model.semantic_name, model.category,
                    relation=PlacementTarget(kind="relative_object", reference=reference.scene_object_id, relation=intent.relation),
                    reference_object=reference,
                )
                obj = patch.operations[0].object
                obj.transform = self._separate(obj, scene, model)
                if operations:
                    # Deterministic initial layout spacing, not robot execution placement.
                    offset = len(operations) * (model.dimensions_m[1] + self.layout.clearance_m)
                    x, y, z = obj.transform.position
                    obj.transform.position = (x, y + offset, z)
                obj.properties.update(intent.properties)
                operations.extend(patch.operations)
        else:
            matches = [o for o in scene.objects if o.scene_object_id == intent.semantic_name]
            if not matches:
                matches = [o for o in scene.objects if o.semantic_name.casefold() == intent.semantic_name.casefold()
                           and o.category.casefold() == intent.category.casefold()]
            if len(matches) != intent.count:
                raise ValueError("scene_edit_object_missing" if len(matches) < intent.count else "scene_edit_object_ambiguous")
            operations = []
            for obj in matches:
                if intent.operation == "remove":
                    operations.append(ScenePatchOperation(action=PatchAction.REMOVE, scene_object_id=obj.scene_object_id))
                    continue
                if reference is not None:
                    transform = self.layout.relative_transform(
                        intent.relation, reference.transform,
                        self.assets.get_model_property(reference.asset_id),
                        self.assets.get_model_property(obj.asset_id),
                    )
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_TRANSFORM, scene_object_id=obj.scene_object_id, transform=transform))
                if intent.properties:
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_PROPERTY, scene_object_id=obj.scene_object_id, properties=intent.properties))
                if reference is None and not intent.properties:
                    raise ValueError("scene_edit_update_missing")
        return ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)

    def _separate(self, obj, scene, model):
        x, y, z = obj.transform.position
        for existing in scene.objects:
            other = self.assets.get_model_property(existing.asset_id)
            ox, oy, _ = existing.transform.position
            if abs(x - ox) < (model.dimensions_m[0] + other.dimensions_m[0]) / 2 + self.layout.clearance_m and abs(y - oy) < (model.dimensions_m[1] + other.dimensions_m[1]) / 2 + self.layout.clearance_m:
                y = oy + (model.dimensions_m[1] + other.dimensions_m[1]) / 2 + self.layout.clearance_m
        return Transform(position=(x, y, z))

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
                relation.relation,
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

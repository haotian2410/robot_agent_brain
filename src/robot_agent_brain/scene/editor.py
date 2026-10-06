from __future__ import annotations

from ..contracts.scene import PatchAction, SceneObject, ScenePatch, ScenePatchOperation, Transform
from ..contracts.task_intent import PlacementTarget, TaskEntity
from .asset_resolver import AssetResolver
import random
from ..ports.asset_catalog import AssetCatalogPort
from .scene_layout import SceneLayoutPolicy
from .transform_editor import translate, rotate
from ..models.motion_policy import MotionPolicy
from ..contracts.turn import SceneEditPlan
from ..grounding.scene_object_selector import SceneObjectSelector
from .scene_manager import SceneManager
from .geometry import world_extents


class SceneEditor:
    """Create semantic scene-layout patches; it never creates robot poses."""

    def __init__(self, assets: AssetCatalogPort, layout: SceneLayoutPolicy | None = None):
        self.assets = assets
        self.layout = layout or SceneLayoutPolicy()
        self.motion_policy = MotionPolicy()

    def edit(self, intent, scene, *, dialogue=None, defaults=None, bindings_override=None) -> ScenePatch:
        if not isinstance(intent, SceneEditPlan):
            return self._edit_one(intent, scene, defaults=defaults)
        # Preview every step locally; publish one atomic patch only on success.
        preview = SceneManager(scene)
        operations = []
        selector = SceneObjectSelector()
        local_bindings = dict(bindings_override or {})
        for edit in intent.operations:
            matches = None
            reference = None
            if edit.target and edit.operation != "add":
                matches = selector.resolve(edit.target, intent.entities, intent.relations, preview.scene, dialogue, local_bindings)
            if edit.reference and edit.target:
                refs = selector.resolve(edit.reference, intent.entities, intent.relations, preview.scene, dialogue, local_bindings)
                if len(refs) != 1:
                    raise ValueError("scene_edit_reference_ambiguous")
                reference = refs[0]
            if edit.operation == "add" and edit.target:
                entity = next(e for e in intent.entities if e.entity_id == edit.target)
                count = entity.count
                if entity.all_available:
                    model = AssetResolver(self.assets).resolve(entity).model
                    count = defaults.initial_counts.get(model.semantic_name) if defaults else None
                    if count is None:
                        raise ValueError("bootstrap_quantity_unspecified: " + model.semantic_name)
                edit = edit.model_copy(update={"semantic_name": entity.semantic_name, "category": entity.category,
                                               "count": count, "properties": {**edit.properties, **({"color":entity.color} if entity.color else {})}})
            patch = self._edit_one(edit, preview.scene, matches=matches, reference=reference, defaults=defaults)
            preview.apply_patch(patch)
            if edit.operation == "add" and edit.target:
                local_bindings[edit.target] = [op.scene_object_id for op in patch.operations if op.action == "add"]
            operations.extend(patch.operations)
        return ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)

    def _edit_one(self, intent, scene, *, matches=None, reference=None, defaults=None) -> ScenePatch:
        """Resolve names to assets/instances before producing a versioned patch."""
        if intent.reference and reference is None:
            refs = [o for o in scene.objects if o.scene_object_id == intent.reference]
            if not refs:
                refs = [o for o in scene.objects if self._matches_name(o, intent.reference)]
            if len(refs) != 1:
                raise ValueError("scene_edit_reference_missing" if not refs else "scene_edit_reference_ambiguous")
            reference = refs[0]
        updated_transforms = []
        if intent.operation == "add":
            binding = AssetResolver(self.assets).resolve(TaskEntity(entity_id="add", semantic_name=intent.semantic_name,
                category=intent.category, color=intent.properties.get("color")))
            model = binding.model
            for key in intent.properties:
                if key not in self.assets.metadata.overridable_properties.get(model.asset_id, []) and binding.properties.get(key) != intent.properties[key]:
                    raise ValueError("asset_property_unsupported: " + key)
            if reference is None and defaults is None:
                raise ValueError("scene_edit_reference_missing: specify the initial placement reference")
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
                    relation=PlacementTarget(kind="relative_object", reference=reference.scene_object_id, relation=intent.relation) if reference else None,
                    reference_object=reference,
                )
                obj = patch.operations[0].object
                if reference is None:
                    obj.transform = self._default_placement(obj, scene, model, defaults, operations)
                else:
                    obj.transform = self._separate(obj, scene, model, extra=updated_transforms)
                updated_transforms.append((obj.transform, model))
                obj.properties.update({**binding.properties, **intent.properties, "aliases":[intent.semantic_name]})
                operations.extend(patch.operations)
        else:
            if matches is None:
                matches = [o for o in scene.objects if o.scene_object_id == intent.semantic_name]
                if not matches:
                    matches = [o for o in scene.objects if self._matches_name(o, intent.semantic_name)
                               and o.category.casefold() == intent.category.casefold()]
                if len(matches) != intent.count:
                    raise ValueError("scene_edit_object_missing" if len(matches) < intent.count else "scene_edit_object_ambiguous")
            operations = []
            for obj in matches:
                if intent.operation == "remove":
                    operations.append(ScenePatchOperation(action=PatchAction.REMOVE, scene_object_id=obj.scene_object_id))
                    continue
                if intent.operation in {"move_relative", "update"} and reference is not None:
                    transform = self.layout.relative_transform(
                        intent.relation, reference.transform,
                        self.assets.get_model_property(reference.asset_id),
                        self.assets.get_model_property(obj.asset_id),
                        obj.transform,
                    )
                    updated_transforms.append((transform, self.assets.get_model_property(obj.asset_id)))
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_TRANSFORM, scene_object_id=obj.scene_object_id, transform=transform))
                elif intent.operation == "translate":
                    model = self.assets.get_model_property(obj.asset_id)
                    distance = intent.distance_m
                    if distance is None:
                        if not intent.motion_scale:
                            raise ValueError("scene_edit_motion_distance_missing")
                        axis = {"left": 0, "right": 0, "front": 1, "back": 1, "up": 2, "down": 2}.get(intent.direction)
                        if axis is None:
                            raise ValueError("scene_edit_motion_direction_missing")
                        distance = model.dimensions_m[axis] * obj.transform.scale[axis] * self.motion_policy.scale_factor(intent.motion_scale)
                    transform = translate(obj.transform, intent.direction, distance, intent.coordinate_frame)
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_TRANSFORM, scene_object_id=obj.scene_object_id, transform=transform))
                elif intent.operation == "rotate":
                    transform = rotate(obj.transform, intent.axis, intent.angle_deg, intent.coordinate_frame)
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_TRANSFORM, scene_object_id=obj.scene_object_id, transform=transform))
                if intent.properties:
                    operations.append(ScenePatchOperation(action=PatchAction.UPDATE_PROPERTY, scene_object_id=obj.scene_object_id, properties=intent.properties))
                if reference is None and intent.operation not in {"translate", "move_relative", "rotate"} and not intent.properties:
                    raise ValueError("scene_edit_update_missing")
        patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)
        # Validate the prospective collection, not each new pose against only
        # old poses. This also permits a group to move into its own vacated space.
        candidate = SceneManager(scene).apply_patch(patch)
        affected = {op.scene_object_id for op in operations if op.action in {PatchAction.ADD, PatchAction.UPDATE_TRANSFORM}}
        for obj in candidate.objects:
            if obj.scene_object_id in affected and self._collides(obj.transform, obj, candidate):
                raise ValueError("scene_edit_transform_collision")
        return patch

    @staticmethod
    def _matches_name(obj, name):
        aliases = obj.properties.get("aliases", [])
        return name.casefold() in {value.casefold() for value in [obj.semantic_name, *aliases] if isinstance(value, str)}

    def _default_placement(self, obj, scene, model, defaults, operations):
        table = next((o for o in scene.objects if o.scene_object_id == defaults.table_object_id), None)
        if table is None:
            raise ValueError("scene_edit_default_surface_missing")
        table_model = self.assets.get_model_property(table.asset_id)
        def vertical_bound(m, upper):
            if m.aabb_m is not None:
                return m.aabb_m[5 if upper else 2]
            if m.asset_id not in self.assets.metadata.center_origin_assets:
                raise ValueError("bootstrap_origin_metadata_missing")
            return m.dimensions_m[2] / (2 if upper else -2)
        z = table.transform.position[2] + vertical_bound(table_model, True) - vertical_bound(model, False)
        xmin,ymin = defaults.workspace_min
        xmax,ymax = defaults.workspace_max
        dx,dy,_ = model.dimensions_m
        if dx >= xmax-xmin or dy >= ymax-ymin:
            raise ValueError("bootstrap_layout_failed")
        candidate_scene = scene.model_copy(update={"objects": [*scene.objects, *[op.object for op in operations if op.action == "add"]]})
        rng = random.Random(len(candidate_scene.objects))
        for _ in range(defaults.max_attempts):
            transform = Transform(position=(rng.uniform(xmin+dx/2,xmax-dx/2), rng.uniform(ymin+dy/2,ymax-dy/2),z))
            if not self._collides(transform, obj, candidate_scene):
                return transform
        raise ValueError("bootstrap_layout_failed")

    def _separate(self, obj, scene, model, excluded=None, extra=None):
        excluded = excluded or set()
        x, y, z = obj.transform.position
        candidates = [(o.transform, self.assets.get_model_property(o.asset_id), o.transform.scale)
                      for o in scene.objects if o.scene_object_id not in excluded]
        candidates += [(transform, other, transform.scale) for transform, other in (extra or [])]
        for _ in range(len(candidates) + 1):
            changed = False
            for other_transform, other, other_scale in candidates:
                ox, oy, oz = other_transform.position
                sx, sy, sz = world_extents(model.dimensions_m, obj.transform)
                osx, osy, osz = world_extents(other.dimensions_m, other_transform)
                if (abs(x - ox) < (sx + osx) / 2 + self.layout.clearance_m
                        and abs(y - oy) < (sy + osy) / 2 + self.layout.clearance_m
                        and abs(z - oz) < (sz + osz) / 2 + self.layout.clearance_m):
                    y = oy + (sy + osy) / 2 + self.layout.clearance_m
                    changed = True
            if not changed:
                break
        return Transform(position=(x, y, z), quaternion_xyzw=obj.transform.quaternion_xyzw, scale=obj.transform.scale)

    def _collides(self, transform, obj, scene):
        model = self.assets.get_model_property(obj.asset_id)
        sx, sy, sz = self._world_extents(model.dimensions_m, transform)
        for other_obj in scene.objects:
            if other_obj.scene_object_id == obj.scene_object_id:
                continue
            other = self.assets.get_model_property(other_obj.asset_id)
            ox, oy, _ = other_obj.transform.position
            x, y, _ = transform.position
            osx, osy, osz = self._world_extents(other.dimensions_m, other_obj.transform)
            oz = other_obj.transform.position[2]
            if (abs(x - ox) < (sx + osx) / 2 and abs(y - oy) < (sy + osy) / 2
                    and abs(transform.position[2] - oz) < (sz + osz) / 2):
                return True
        return False

    _world_extents = staticmethod(world_extents)

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
                relation.relation or "free_space",
                reference_object.transform,
                reference_model,
                model,
                transform,
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

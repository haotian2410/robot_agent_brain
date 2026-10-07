from __future__ import annotations

from ..contracts.scene import PatchAction, SceneObject, ScenePatch, ScenePatchOperation, Transform
from ..contracts.task_intent import PlacementTarget, TaskEntity
from .asset_resolver import AssetResolver
import random
from dataclasses import dataclass, field
from ..ports.asset_catalog import AssetCatalogPort
from .scene_layout import SceneLayoutPolicy
from .transform_editor import translate, rotate
from ..models.motion_policy import MotionPolicy
from ..contracts.turn import SceneEditPlan
from ..grounding.scene_object_selector import SceneObjectSelector
from .scene_manager import SceneManager
from .geometry import world_extents, world_bounds
from .spatial_facts import SpatialFactResolver


@dataclass
class SceneEditResult:
    patch: ScenePatch
    focus_object_ids: list[str] = field(default_factory=list)
    created_object_ids: list[str] = field(default_factory=list)
    deleted_object_ids: list[str] = field(default_factory=list)
    entity_bindings: dict[str, list[str]] = field(default_factory=dict)


class SceneEditor:
    """Create semantic scene-layout patches; it never creates robot poses."""

    def __init__(self, assets: AssetCatalogPort, layout: SceneLayoutPolicy | None = None, *, seed=0):
        self.assets = assets
        self.layout = layout or SceneLayoutPolicy()
        self.seed = seed
        self.motion_policy = MotionPolicy()

    def edit(self, intent, scene, *, dialogue=None, defaults=None, bindings_override=None) -> ScenePatch:
        """Compatibility entry point for callers consuming only the patch."""
        return self.edit_result(intent, scene, dialogue=dialogue, defaults=defaults,
                                bindings_override=bindings_override).patch

    def edit_result(self, intent, scene, *, dialogue=None, defaults=None, bindings_override=None) -> SceneEditResult:
        if not isinstance(intent, SceneEditPlan):
            patch = self._edit_one(intent, scene, defaults=defaults)
            return self._result(patch, {})
        # Preview every step locally; publish one atomic patch only on success.
        preview = SceneManager(scene)
        operations = []
        selector = SceneObjectSelector(category_aliases=self.assets.metadata.category_aliases)
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
        patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)
        SceneManager(scene).apply_patch(patch)
        return self._result(patch, local_bindings)

    @staticmethod
    def _result(patch, bindings):
        # These operations are emitted only for each edit's semantic target;
        # references are never mutated or selected as focus by the editor.
        created = list(dict.fromkeys(op.scene_object_id for op in patch.operations if op.action == PatchAction.ADD))
        deleted = list(dict.fromkeys(op.scene_object_id for op in patch.operations if op.action == PatchAction.REMOVE))
        focus = list(dict.fromkeys(op.scene_object_id for op in patch.operations
                                  if op.action != PatchAction.REMOVE and op.scene_object_id not in deleted))
        live_bindings = {key:[i for i in ids if i not in deleted] for key,ids in bindings.items()}
        return SceneEditResult(patch, focus, created, deleted, live_bindings)

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
                    defaults=defaults,
                )
                obj = patch.operations[0].object
                if reference is None:
                    obj.transform = self._default_placement(obj, scene, model, defaults, operations)
                else:
                    obj.transform = self._separate(obj, scene, model, extra=updated_transforms,
                                                   defaults=defaults, relation=intent.relation)
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
        facts = self._facts(defaults)
        for obj in candidate.objects:
            if obj.scene_object_id not in affected:
                continue
            support = facts.infer_support(obj, candidate)
            if support is None and intent.operation == "add" and intent.relation in {"left_of", "right_of", "front_of", "behind"}:
                raise ValueError("scene_edit_support_unknown: relative addition is outside the supported footprint")
            if support is not None:
                operations.append(ScenePatchOperation(action=PatchAction.UPDATE_PROPERTY,
                    scene_object_id=obj.scene_object_id,
                    properties={"support": support, "support_relation": "on", "support_evaluated": True}))
            elif not facts.is_surface(obj) and facts.can_evaluate(obj, candidate):
                # A checked but unproven on-relation is not a positive fact.
                # Distinguish it from an uploaded snapshot without evaluation.
                operations.append(ScenePatchOperation(action=PatchAction.UPDATE_PROPERTY,
                    scene_object_id=obj.scene_object_id, properties={"support_evaluated": True}))
        patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)
        SceneManager(scene).apply_patch(patch)
        return patch

    def _facts(self, defaults=None):
        return SpatialFactResolver(self.assets, support_contact_tolerance_m=defaults.support_contact_tolerance_m if defaults else .001)

    @staticmethod
    def _matches_name(obj, name):
        aliases = obj.properties.get("aliases", [])
        return name.casefold() in {value.casefold() for value in [obj.semantic_name, *aliases] if isinstance(value, str)}

    def _default_placement(self, obj, scene, model, defaults, operations):
        table = next((o for o in scene.objects if o.scene_object_id == defaults.table_object_id), None)
        if table is None:
            raise ValueError("scene_edit_default_surface_missing")
        facts = self._facts(defaults)
        z = facts.support_transform(model, table, x=0, y=0, existing=obj.transform).position[2]
        xmin,ymin = defaults.workspace_min
        xmax,ymax = defaults.workspace_max
        dx,dy,_ = model.dimensions_m
        if dx >= xmax-xmin or dy >= ymax-ymin:
            raise ValueError("bootstrap_layout_failed")
        candidate_scene = scene.model_copy(update={"objects": [*scene.objects, *[op.object for op in operations if op.action == "add"]]})
        rng = random.Random(f"{self.seed}:{len(candidate_scene.objects)}")
        for _ in range(defaults.max_attempts):
            transform = Transform(position=(rng.uniform(xmin+dx/2,xmax-dx/2), rng.uniform(ymin+dy/2,ymax-dy/2),z))
            placed = obj.model_copy(update={"transform": transform})
            if facts.footprint_contains(placed, table) and not self._collides(transform, obj, candidate_scene, clearance=defaults.clearance_m):
                return transform
        raise ValueError("bootstrap_layout_failed")

    def _separate(self, obj, scene, model, excluded=None, extra=None, *, defaults=None, relation=None):
        excluded = excluded or set()
        x, y, z = obj.transform.position
        candidates = [(o.transform, self.assets.get_model_property(o.asset_id), o.transform.scale)
                      for o in scene.objects if o.scene_object_id not in excluded]
        candidates += [(transform, other, transform.scale) for transform, other in (extra or [])]
        sx, sy, sz = world_extents(model.dimensions_m, obj.transform)
        # Search perpendicular to the specified direction. Never repair a
        # collision by reversing the requested front/behind/left/right relation.
        axis = 0 if relation in {"front_of", "behind"} else 1
        spacing = (sx if axis == 0 else sy) + self.layout.clearance_m
        limit = defaults.max_attempts if defaults else 2 * len(candidates) + 3
        for attempt in range(limit):
            offset = 0 if attempt == 0 else ((attempt + 1) // 2) * spacing * (1 if attempt % 2 else -1)
            cx, cy = (x + offset, y) if axis == 0 else (x, y + offset)
            if defaults and not (defaults.workspace_min[0] <= cx-sx/2 and cx+sx/2 <= defaults.workspace_max[0]
                                 and defaults.workspace_min[1] <= cy-sy/2 and cy+sy/2 <= defaults.workspace_max[1]):
                continue
            collision = False
            trial = obj.transform.model_copy(update={"position": (cx, cy, z)})
            low, high = world_bounds(model, trial, center_origin=True)
            for other_transform, other, _ in candidates:
                other_low, other_high = world_bounds(other, other_transform, center_origin=True)
                if all(low[i] < other_high[i] + (self.layout.clearance_m if i < 2 else -1e-9)
                       and other_low[i] < high[i] + (self.layout.clearance_m if i < 2 else -1e-9) for i in range(3)):
                    collision = True
                    break
            if not collision:
                return Transform(position=(cx, cy, z), quaternion_xyzw=obj.transform.quaternion_xyzw, scale=obj.transform.scale)
        raise ValueError("bootstrap_layout_failed" if defaults else "scene_edit_layout_collision")

    def _collides(self, transform, obj, scene, *, clearance=0):
        model = self.assets.get_model_property(obj.asset_id)
        low, high = world_bounds(model, transform, center_origin=True)
        for other_obj in scene.objects:
            if other_obj.scene_object_id == obj.scene_object_id:
                continue
            other = self.assets.get_model_property(other_obj.asset_id)
            other_low, other_high = world_bounds(other, other_obj.transform, center_origin=True)
            if all(low[i] < other_high[i] + (clearance if i < 2 else -1e-9)
                   and other_low[i] < high[i] + (clearance if i < 2 else -1e-9) for i in range(3)):
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
        defaults=None,
    ) -> ScenePatch:
        model = self.assets.get_model_property(asset_id)
        transform = Transform()
        if relation is not None and relation.reference is not None:
            if reference_object is None:
                raise ValueError("scene_edit_reference_missing")
            reference_model = self.assets.get_model_property(reference_object.asset_id)
            if relation.relation in {"left_of", "right_of", "front_of", "behind"}:
                facts = self._facts(defaults)
                support_id = facts.infer_support(reference_object, scene)
                if support_id is None and defaults is not None:
                    support_id = defaults.table_object_id
                support = next((o for o in scene.objects if o.scene_object_id == support_id), None)
                if support is None:
                    raise ValueError("scene_edit_support_unknown")
                transform = facts.support_transform(model, support, x=0, y=0)
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

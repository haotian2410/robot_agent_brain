"""Atomic component scene edits; no robot motion or Control execution."""
import random
from dataclasses import dataclass, field

from ..contracts.scene import ScenePatch, ScenePatchOperation, SceneComponent
from ..contracts.turn import SceneEditPlan
from ..grounding.scene_object_selector import SceneObjectSelector
from ..models.motion_policy import MotionPolicy
from .asset_resolver import AssetResolver
from .bootstrapper import make_object, IDENTITY
from .component_access import SceneIndex
from .geometry import world_bounds
from .scene_graph import WorldTransform, world_transform, local_from_world
from .scene_layout import SceneLayoutPolicy
from .scene_manager import SceneManager
from .spatial_facts import SpatialFactResolver
from .transform_editor import translate, rotate


@dataclass
class SceneEditResult:
    patch: ScenePatch
    focus_object_ids: list[int] = field(default_factory=list)
    created_object_ids: list[int] = field(default_factory=list)
    deleted_object_ids: list[int] = field(default_factory=list)
    entity_bindings: dict[str, list[int]] = field(default_factory=dict)


class SceneEditor:
    def __init__(self, assets, layout=None, *, seed=0, aliases=None, category_aliases=None):
        self.assets, self.seed = assets, seed
        self.layout = layout or SceneLayoutPolicy()
        self.aliases, self.category_aliases = aliases or {}, category_aliases or {}
        self.motion_policy = MotionPolicy()

    def edit(self, intent, scene, **kwargs):
        return self.edit_result(intent, scene, **kwargs).patch

    def edit_result(self, intent, scene, *, dialogue=None, defaults=None, bindings_override=None,
                    seen_scene_object_ids=None, next_scene_object_id=None):
        if not isinstance(intent, SceneEditPlan):
            raise ValueError("scene_edit_plan_required")
        preview = SceneManager(scene, seen_scene_object_ids=seen_scene_object_ids,
                               next_scene_object_id=next_scene_object_id)
        selector = SceneObjectSelector(aliases=self.aliases, category_aliases=self.category_aliases)
        bindings = dict(bindings_override or {})
        all_operations = []
        for edit in intent.operations:
            if edit.properties:
                raise ValueError("scene_edit_properties_unsupported: shared Scene has no arbitrary properties")
            current = preview.scene
            reference = None
            if edit.reference is not None:
                references = selector.resolve(edit.reference, intent.entities, intent.relations,
                                              current, dialogue, bindings)
                if len(references) != 1:
                    raise ValueError("scene_edit_reference_ambiguous")
                reference = references[0]
            entity = next(item for item in intent.entities if item.entity_id == edit.target)
            if edit.operation == "add":
                operations = self._add(edit, entity, current, preview.next_scene_object_id, reference, defaults)
            else:
                matches = selector.resolve(edit.target, intent.entities, intent.relations, current, dialogue, bindings)
                operations = self._modify(edit, matches, reference, current)
            patch = ScenePatch(scene_id=current.scene_id, base_scene_version=current.scene_version, operations=operations)
            candidate = SceneManager(current, seen_scene_object_ids=preview.seen_scene_object_ids,
                                     next_scene_object_id=preview.next_scene_object_id).apply_patch(patch)
            affected = {op.object_id_in_scene for op in operations if op.action == "add_object"
                        or op.action == "upsert_component" and op.component.component_type == "Transform"}
            facts = self._facts(defaults)
            for identifier in affected:
                index = SceneIndex(candidate)
                obj = index.object(identifier)
                if self._overlaps(obj, candidate):
                    raise ValueError("scene_edit_transform_collision")
                semantic = index.semantic(identifier)
                if semantic is None:
                    continue
                support = facts.infer_support(obj, candidate)
                if edit.operation == "add" and (reference is None or edit.relation in {"left_of", "right_of", "front_of", "behind"}) and support is None:
                    raise ValueError("scene_edit_support_unknown")
                operations.append(ScenePatchOperation(action="upsert_component", object_id_in_scene=identifier,
                    component=SceneComponent(component_type="Semantic",
                        properties={**semantic.model_dump(mode="json"), "support": support})))
            patch = ScenePatch(scene_id=current.scene_id, base_scene_version=current.scene_version, operations=operations)
            preview.apply_patch(patch)
            if edit.operation == "add":
                bindings[edit.target] = [op.object_id_in_scene for op in operations if op.action == "add_object"]
            all_operations.extend(operations)
        result = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=all_operations)
        SceneManager(scene, seen_scene_object_ids=seen_scene_object_ids,
                     next_scene_object_id=next_scene_object_id).apply_patch(result)
        created = list(dict.fromkeys(op.object_id_in_scene for op in all_operations if op.action == "add_object"))
        deleted = list(dict.fromkeys(op.object_id_in_scene for op in all_operations if op.action == "remove_object"))
        focus = list(dict.fromkeys(op.object_id_in_scene for op in all_operations
                                   if op.action != "remove_object" and op.object_id_in_scene not in deleted))
        return SceneEditResult(result, focus, created, deleted,
                               {key: [i for i in ids if i not in deleted] for key, ids in bindings.items()})

    def _facts(self, defaults=None):
        return SpatialFactResolver(self.assets, support_contact_tolerance_m=defaults.support_contact_tolerance_m if defaults else .001)

    def _modify(self, edit, matches, reference, scene):
        operations = []
        facts = self._facts()
        for obj in matches:
            identifier = obj.object_id_in_scene
            if edit.operation == "remove":
                operations.append(ScenePatchOperation(action="remove_object", object_id_in_scene=identifier))
                continue
            world = world_transform(scene, identifier)
            if edit.operation == "translate":
                distance = edit.distance_m
                if distance is None:
                    if edit.motion_scale is None:
                        raise ValueError("scene_edit_motion_distance_missing")
                    model = facts.asset(obj, scene)
                    axis = {"left": 0, "right": 0, "front": 1, "back": 1, "up": 2, "down": 2}[edit.direction]
                    distance = model.dimensions_m[axis] * world.scale[axis] * self.motion_policy.scale_factor(edit.motion_scale)
                moved = translate(world, edit.direction, distance, edit.coordinate_frame)
            elif edit.operation == "rotate":
                moved = rotate(world, edit.axis, edit.angle_deg, edit.coordinate_frame)
            elif edit.operation in {"move_relative", "update"} and reference is not None:
                moved = self.layout.relative_transform(edit.relation, world_transform(scene, reference.object_id_in_scene),
                    facts.asset(reference, scene), facts.asset(obj, scene), world)
            else:
                raise ValueError("scene_edit_update_missing")
            local = local_from_world(scene, identifier, moved)
            operations.append(ScenePatchOperation(action="upsert_component", object_id_in_scene=identifier,
                component=SceneComponent(component_type="Transform", properties=local.model_dump(mode="json"))))
        return operations

    def _add(self, edit, entity, scene, next_id, reference, defaults):
        binding = AssetResolver(self.assets, aliases=self.aliases, category_aliases=self.category_aliases).resolve(entity)
        model = binding.model
        count = entity.count
        if entity.all_available:
            count = defaults.initial_counts.get(model.semantic_name) if defaults else None
            if count is None:
                raise ValueError("bootstrap_quantity_unspecified: " + model.semantic_name)
        if reference is None and defaults is None:
            raise ValueError("scene_edit_reference_missing")
        operations = []
        temporary = scene
        for offset in range(count):
            identifier = next_id + offset
            if identifier > 2**53 - 1:
                raise ValueError("scene_object_ids_exhausted")
            position = self._placement(model, temporary, reference, edit.relation, defaults, identifier)
            obj = make_object(identifier, model.semantic_name, model.metadata_ref, position,
                              category=model.category or entity.category)
            operations.append(ScenePatchOperation(action="add_object", object_id_in_scene=identifier, object=obj))
            temporary = temporary.model_copy(update={"objects": [*temporary.objects, obj]})
        return operations

    def _placement(self, model, scene, reference, relation, defaults, identifier):
        facts, index = self._facts(defaults), SceneIndex(scene)
        planar = relation in {"left_of", "right_of", "front_of", "behind"}
        support = None
        if reference is None:
            try:
                support = index.object(defaults.table_object_id)
            except LookupError as exc:
                raise ValueError("scene_edit_default_surface_missing") from exc
        elif planar:
            support_id = (reference.object_id_in_scene if facts.is_surface(reference, scene)
                          else facts.infer_support(reference, scene))
            if support_id is None and defaults is not None:
                support_id = defaults.table_object_id
            if support_id is None:
                raise ValueError("scene_edit_support_unknown")
            support = index.object(support_id)
        world = facts.support_transform(model, support, scene, x=0, y=0) if support is not None else WorldTransform((0, 0, 0), IDENTITY)
        if reference is not None:
            world = self.layout.relative_transform(relation, world_transform(scene, reference.object_id_in_scene),
                facts.asset(reference, scene), model, world)
        origin_low, origin_high = world_bounds(model, WorldTransform((0, 0, 0), world.linear))
        rng = random.Random(f"{self.seed}:{identifier}")
        limit = defaults.max_attempts if defaults else 2 * len(scene.objects) + 5
        for attempt in range(limit):
            if reference is None:
                limits = [(defaults.workspace_min[i] - origin_low[i], defaults.workspace_max[i] - origin_high[i]) for i in (0, 1)]
                if any(a > b for a, b in limits):
                    raise ValueError("bootstrap_layout_failed")
                position = (rng.uniform(*limits[0]), rng.uniform(*limits[1]), world.position[2])
            else:
                axis = 0 if relation in {"front_of", "behind"} else 1
                spacing = origin_high[axis] - origin_low[axis] + self.layout.clearance_m
                step = 0 if attempt == 0 else ((attempt + 1) // 2) * (1 if attempt % 2 else -1)
                position = tuple(value + (step * spacing if i == axis else 0) for i, value in enumerate(world.position))
            obj = make_object(identifier, model.semantic_name, model.metadata_ref, position, category=model.category or "object")
            candidate = scene.model_copy(update={"objects": [*scene.objects, obj]})
            box = world_bounds(model, WorldTransform(position, world.linear))
            if defaults and any(box[0][i] < defaults.workspace_min[i] or box[1][i] > defaults.workspace_max[i] for i in (0, 1)):
                continue
            if support is not None and not facts.footprint_contains(obj, support, candidate):
                continue
            if not self._overlaps(obj, candidate, clearance=defaults.clearance_m if defaults else self.layout.clearance_m):
                return position
        raise ValueError("scene_edit_layout_collision")

    def _overlaps(self, obj, scene, *, clearance=0):
        # Existing conservative AABB layout guard, not physics collision checking.
        facts = self._facts()
        try:
            low, high = world_bounds(facts.asset(obj, scene), world_transform(scene, obj.object_id_in_scene))
        except (ValueError, LookupError):
            return False  # Unknown resource geometry is not asserted as contact evidence.
        for other in scene.objects:
            if other.object_id_in_scene == obj.object_id_in_scene:
                continue
            try:
                olow, ohigh = world_bounds(facts.asset(other, scene), world_transform(scene, other.object_id_in_scene))
            except (ValueError, LookupError):
                continue
            if all(low[i] < ohigh[i] + (clearance if i < 2 else -1e-9)
                   and olow[i] < high[i] + (clearance if i < 2 else -1e-9) for i in range(3)):
                return True
        return False

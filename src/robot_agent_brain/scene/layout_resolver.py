"""Resolve normalized layout slots to existing/new semantic instances.

Owns asset expansion, stable instance selection, world-space slot mapping and
candidate geometry validation. Shared SceneEditor policies provide replacement
and geometry primitives; only the session/SceneEditor transaction publishes.
"""
from __future__ import annotations
import math

from ..contracts.arrangement import ArrangementSpec, LayoutPlan, LayoutResolution
from ..contracts.scene import ScenePatch, ScenePatchOperation
from .scene_manager import SceneManager
from .component_access import SceneIndex
from .asset_resolver import AssetResolver
from .bootstrapper import make_object
from .geometry import world_bounds
from .scene_graph import WorldTransform, world_transform, local_from_world
from ..grounding.scene_reference_resolver import SceneReferenceResolver


class LayoutResolver:
    def __init__(self, *, editor=None):
        # Shared asset/geometry/replace policy; never publishes to the platform.
        self.editor = editor

    def resolve_candidate(self, spec, plan, scene, *, defaults=None,
                          seen_scene_object_ids=None, next_scene_object_id=None, instance_ids=None):
        """Search spacing only when explicitly authorized; publish no trials.

        Regular patterns retain their center, region, ordering and exact count.
        Automatic circles search their derived radius; fixed radii and free
        paths are not retried. Every trial undergoes the full geometry checks.
        """
        auto_radius = spec.pattern.kind == "circle" and spec.pattern.radius_m is None
        adaptive = (spec.spacing.mode == "auto" and spec.spacing.auto
                    and (spec.pattern.kind in {"line", "grid", "checker", "alternating"} or auto_radius)
                    and spec.operation != "replace")
        attempts = 48 if adaptive else 1
        for attempt in range(attempts):
            try:
                result = self._resolve_candidate_once(spec, plan, scene, defaults=defaults,
                    seen_scene_object_ids=seen_scene_object_ids,
                    next_scene_object_id=next_scene_object_id, instance_ids=instance_ids,
                    spacing_factor=1.1 ** attempt)
                if adaptive:
                    quantity = "radius" if auto_radius else "spacing"
                    result.assumptions.append(f"layout_{quantity}_search_attempts={attempt + 1}")
                    result.assumptions.append(f"layout_{quantity}_search=authorized_auto")
                return result
            except ValueError as error:
                # Increasing a centered regular pattern cannot repair capacity
                # or support failures. Never retry identity/schema/asset errors.
                if str(error) != "scene_layout_collision" or attempt + 1 == attempts:
                    raise

    def _resolve_candidate_once(self, spec, plan, scene, *, defaults=None,
                          seen_scene_object_ids=None, next_scene_object_id=None,
                          instance_ids=None, spacing_factor=1.0):
        """Resolve assets, instances and exact world poses into an uncommitted patch."""
        from .editor import SceneEditResult
        editor = self.editor
        if editor is None:
            raise ValueError("scene_layout_resolver_not_configured")
        from ..planning.layout_planner import expanded_aliases, pattern_yaws
        from ..contracts.task_intent import TaskEntity
        if spec.operation == "replace" and spec.basis == "current":
            aliases = expanded_aliases(spec)
            if instance_ids is None or len(instance_ids) != len(aliases) or len(set(instance_ids)) != len(instance_ids):
                raise ValueError("scene_layout_instance_count_mismatch")
            preview = SceneManager(scene, seen_scene_object_ids=seen_scene_object_ids,
                                   next_scene_object_id=next_scene_object_id)
            operations, new_ids, assumptions = [], [], []
            for identifier, alias in zip(instance_ids, aliases):
                entity = TaskEntity(entity_id=alias, semantic_name=alias, category="object")
                binding = AssetResolver(editor.assets, aliases=editor.aliases,
                    category_aliases=editor.category_aliases,
                    default_refs=editor.default_scene_edit_assets).resolve(entity, allow_default=True, infer_category=True)
                replacements = editor._replace([SceneIndex(preview.scene).object(identifier)], entity,
                    preview.scene, preview.next_scene_object_id, resolved_model=binding.model)
                new_ids.extend(op.object_id_in_scene for op in replacements if op.action == "add_object")
                assumptions.extend(binding.assumptions)
                preview.apply_patch(ScenePatch(scene_id=scene.scene_id,
                    base_scene_version=preview.scene.scene_version, operations=replacements))
                operations.extend(replacements)
            # Reuse the exact placement path on a private preview. Intermediate
            # replacements are never published or allowed to consume live IDs.
            placed = self.resolve_candidate(spec.model_copy(update={"operation": "rearrange"}), plan,
                preview.scene, defaults=defaults, instance_ids=new_ids,
                seen_scene_object_ids=preview.seen_scene_object_ids,
                next_scene_object_id=preview.next_scene_object_id)
            operations.extend(placed.patch.operations)
            patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)
            SceneManager(scene, seen_scene_object_ids=seen_scene_object_ids,
                         next_scene_object_id=next_scene_object_id).apply_patch(patch)
            return SceneEditResult(patch, new_ids, new_ids, list(instance_ids),
                                   assumptions=assumptions + placed.assumptions,
                                   adjusted_layout_spacing_m=placed.adjusted_layout_spacing_m)
        if spec.operation not in {"create", "append", "rearrange"} or spec.basis != "current":
            raise ValueError("scene_layout_operation_not_implemented")
        if spec.region.kind not in {"surface_region", "around", "near", "relative"} or spec.constraints.support != "on_surface":
            raise ValueError("scene_layout_region_requires_resolver_support")
        import math
        from .scene_graph import quaternion_matrix
        if spec.pattern.kind not in {"line", "grid", "checker", "alternating", "circle", "ring", "arc", "scatter", "text", "custom"}:
            raise ValueError("scene_layout_pattern_requires_resolver_support")
        if spec.pattern.kind == "custom" and not spec.pattern.path:
            raise ValueError("scene_layout_custom_requires_normalized_path")
        manager = SceneManager(scene, seen_scene_object_ids=seen_scene_object_ids,
                               next_scene_object_id=next_scene_object_id)
        reference_resolver = SceneReferenceResolver(editor.reference_resolver.catalog, assets=editor.assets,
                                     aliases=editor.aliases, table_metadata_ref=editor.table_metadata_ref)
        ref = reference_resolver.resolve(spec.region.surface_ref, scene=scene)
        support = SceneIndex(scene).object(ref.object_id)
        facts = editor._facts(defaults)
        if not facts.is_surface(support, scene):
            raise ValueError("scene_layout_support_invalid")
        aliases = expanded_aliases(spec)
        bindings = []
        for alias in aliases:
            entity = TaskEntity(entity_id=alias, semantic_name=alias, category="object")
            bindings.append(AssetResolver(editor.assets, aliases=editor.aliases,
                category_aliases=editor.category_aliases,
                default_refs=editor.default_scene_edit_assets).resolve(entity, allow_default=True, infer_category=True))
        if len(plan.slots) != len(bindings):
            raise ValueError("scene_layout_count_conflict")
        models = [binding.model for binding in bindings]
        rearranging = spec.operation == "rearrange"
        existing = []
        if rearranging:
            if instance_ids is None or len(instance_ids) != len(plan.slots) or len(set(instance_ids)) != len(instance_ids):
                raise ValueError("scene_layout_instance_count_mismatch")
            index = SceneIndex(scene)
            existing = [index.object(oid) for oid in instance_ids]
            models = [facts.asset(obj, scene) for obj in existing]
            for obj, model, requested in zip(existing, models, bindings):
                oid = obj.object_id_in_scene
                if model.semantic_name != requested.model.semantic_name:
                    raise ValueError("scene_layout_rearrange_asset_mismatch")
                if index.robot_driver(oid) or index.component(oid, "RobotAttachment") or index.metadata_type(oid) == "robot":
                    raise ValueError("scene_layout_rearrange_platform_unsupported")
                if index.transform(oid).parent in instance_ids:
                    raise ValueError("scene_layout_nested_members_unsupported")
        low, high = world_bounds(facts.asset(support, scene), world_transform(scene, ref.object_id))
        lo, hi = list(low[:2]), list(high[:2])
        side = spec.region.side
        axis = 0 if side in {"left_half", "right_half"} else 1
        if spec.region.kind == "relative":
            anchor_ref = reference_resolver.resolve(spec.region.anchor_ref, scene=scene)
            anchor = SceneIndex(scene).object(anchor_ref.object_id)
            anchor_low, anchor_high = world_bounds(facts.asset(anchor, scene),
                                                  world_transform(scene, anchor_ref.object_id))
            # Restrict the tabletop by the anchor's actual rotated/scaled AABB,
            # not by the table midpoint or a guessed fixed offset. All member
            # footprints must remain on the requested side of the anchor.
            clearance = spec.constraints.min_clearance_m
            if side in {"left_half", "back_half"}:
                hi[axis] = min(hi[axis], anchor_low[axis] - clearance)
            elif side in {"right_half", "front_half"}:
                lo[axis] = max(lo[axis], anchor_high[axis] + clearance)
            else:
                raise ValueError("scene_layout_relative_direction_missing")
            if any(lo[i] >= hi[i] for i in range(2)):
                raise ValueError("scene_layout_capacity_exceeded")
        elif side not in {"any", "center"}:
            mid = (lo[axis] + hi[axis]) / 2
            if side in {"left_half", "back_half"}:
                hi[axis] = mid
            else:
                lo[axis] = mid
        center = [(lo[i] + hi[i]) / 2 for i in range(2)]
        if spec.region.kind in {"around", "near"}:
            anchor_ref = reference_resolver.resolve(spec.region.anchor_ref, scene=scene)
            anchor = SceneIndex(scene).object(anchor_ref.object_id)
            anchor_low, anchor_high = world_bounds(facts.asset(anchor, scene),
                                                  world_transform(scene, anchor_ref.object_id))
            center = [(anchor_low[i] + anchor_high[i]) / 2 for i in range(2)]
            if not all(lo[i] <= center[i] <= hi[i] for i in range(2)):
                raise ValueError("scene_layout_region_unresolved")
        for axis, requested in enumerate((spec.region.width_m, spec.region.depth_m)):
            if requested is not None:
                if requested > hi[axis] - lo[axis]:
                    raise ValueError("scene_layout_capacity_exceeded")
                lo[axis], hi[axis] = center[axis] - requested / 2, center[axis] + requested / 2
        yaws = pattern_yaws(spec, [(s.u, s.v) for s in plan.slots],
                            scale=(hi[0] - lo[0], hi[1] - lo[1]))
        if any(not math.isfinite(value) for value in yaws):
            raise ValueError("scene_layout_orientation_invalid")
        quaternions = [(0., 0., math.sin(math.radians(yaw) / 2), math.cos(math.radians(yaw) / 2))
                       for yaw in yaws]
        linears = [quaternion_matrix(q) for q in quaternions]
        if rearranging:
            scales = [world_transform(scene, oid).scale for oid in instance_ids]
            linears = [tuple(tuple(rotation[i][j] * scale[j] for j in range(3)) for i in range(3))
                       for rotation, scale in zip(linears, scales)]
        sizes = [world_bounds(model, WorldTransform((0, 0, 0), linear))
                 for model, linear in zip(models, linears)]
        extent = max(max(b[1][i] - b[0][i] for i in (0, 1)) for b in sizes)
        spacing = spec.spacing.value_m
        if spec.spacing.mode == "auto":
            spacing = (extent + spec.constraints.min_clearance_m) * spacing_factor
        elif spec.spacing.mode == "edge":
            spacing += extent
        unique = [sorted({getattr(s, name) for s in plan.slots}) for name in ("u", "v")]
        spans = [spacing * (len(values) - 1) for values in unique]
        if spec.pattern.kind in {"circle", "arc", "ring"}:
            radius = ((spec.pattern.inner_radius_m + spec.pattern.outer_radius_m) / 2
                      if spec.pattern.kind == "ring" else spec.pattern.radius_m)
            if radius is None:
                # Bound every footprint about its actual object origin, including
                # asymmetric assets and rotation/scale. Chord separation then
                # gives a conservative starting radius; normal candidate checks
                # still decide support, region capacity and existing collisions.
                footprint_radius = max(math.hypot(x, y) for box in sizes
                                       for x in (box[0][0], box[1][0])
                                       for y in (box[0][1], box[1][1]))
                clearance = spec.constraints.min_clearance_m
                count = len(plan.slots)
                radius = ((2 * footprint_radius + clearance) / (2 * math.sin(math.pi / count))
                          if count > 1 else footprint_radius + clearance)
                if spec.region.kind in {"around", "near"}:
                    anchor_radius = max(math.hypot(x - center[0], y - center[1])
                                        for x in (anchor_low[0], anchor_high[0])
                                        for y in (anchor_low[1], anchor_high[1]))
                    radius = max(radius, anchor_radius + footprint_radius + clearance)
                radius *= spacing_factor
            # Circular generators use normalized radius .45. Preserve the
            # requested physical radius rather than stretching each axis.
            spans = [radius / .45, radius / .45]
        path_region = spec.pattern.kind in {"scatter", "text", "custom"}
        if path_region:
            # Slots describe the region available to object origins, not the
            # bare tabletop boundary. Use a common inset for every member so
            # mixed-size assets do not distort the path on a per-slot basis.
            # Non-centred OLS bounds need asymmetric insets.
            footprint_low = [min(box[0][axis] for box in sizes) for axis in (0, 1)]
            footprint_high = [max(box[1][axis] for box in sizes) for axis in (0, 1)]
            if spec.orientation.mode == "follow_pattern":
                # Changing the available region changes tangent yaws. Bound
                # every possible yaw first, avoiding circular fit iteration.
                radius = max(math.hypot(x, y) for box in sizes
                             for x in (box[0][0], box[1][0])
                             for y in (box[0][1], box[1][1]))
                footprint_low, footprint_high = [-radius] * 2, [radius] * 2
            origin_low = [lo[a] + spec.region.margin_m - footprint_low[a] + 1e-9 for a in (0, 1)]
            origin_high = [hi[a] - spec.region.margin_m - footprint_high[a] - 1e-9 for a in (0, 1)]
            if any(origin_low[a] >= origin_high[a] for a in (0, 1)):
                raise ValueError("scene_layout_capacity_exceeded")
            if spec.pattern.kind == "text":
                # Font outlines were normalized with one common scale. Keep
                # that metric in world space: independently stretching X/Y to
                # a rectangular table changes the glyph. Inscribe a square
                # in the footprint-safe origin region, without resizing assets.
                span = min(origin_high[a] - origin_low[a] for a in (0, 1))
                midpoint = [(origin_low[a] + origin_high[a]) / 2 for a in (0, 1)]
                origin_low = [value - span / 2 for value in midpoint]
                origin_high = [value + span / 2 for value in midpoint]
            if spec.orientation.mode == "follow_pattern":
                yaws = pattern_yaws(spec, [(s.u, s.v) for s in plan.slots],
                    scale=tuple(origin_high[a] - origin_low[a] for a in (0, 1)))
                quaternions = [(0., 0., math.sin(math.radians(yaw) / 2), math.cos(math.radians(yaw) / 2))
                               for yaw in yaws]
                linears = [quaternion_matrix(q) for q in quaternions]
                if rearranging:
                    linears = [tuple(tuple(rotation[i][j] * scale[j] for j in range(3)) for i in range(3))
                               for rotation, scale in zip(linears, scales)]
        operations, ids = [], []
        candidate = scene
        for index, (slot, model) in enumerate(zip(plan.slots, models)):
            linear, quaternion = linears[index], quaternions[index]
            if path_region:
                xy = [origin_low[axis] + value * (origin_high[axis] - origin_low[axis])
                      for axis, value in enumerate((slot.u, slot.v))]
            else:
                xy = [center[axis] + (value - .5) * spans[axis]
                      for axis, value in enumerate((slot.u, slot.v))]
            identifier = instance_ids[index] if rearranging else manager.next_scene_object_id + index
            pose = facts.support_transform(model, support, scene, x=xy[0], y=xy[1],
                                           existing=WorldTransform((0, 0, 0), linear))
            if rearranging:
                obj = existing[index].model_copy(deep=True)
                transform = next(c for c in obj.components if c.component_type == "Transform")
                transform.properties.update(local_from_world(scene, identifier, pose).model_dump(mode="json"))
                semantic = next(c for c in obj.components if c.component_type == "Semantic")
                semantic.properties["support"] = ref.object_id
                operations.extend([
                    ScenePatchOperation(action="upsert_component", object_id_in_scene=identifier, component=transform),
                    ScenePatchOperation(action="upsert_component", object_id_in_scene=identifier, component=semantic),
                ])
                candidate = candidate.model_copy(update={"objects": [
                    obj if o.object_id_in_scene == identifier else o for o in candidate.objects]})
            else:
                obj = make_object(identifier, model.semantic_name, model.metadata_ref,
                                  pose.position, category=model.category or "object", support=ref.object_id,
                                  asset_type=model.asset_type if getattr(editor.assets, "supports_features", False) else None)
                next(c for c in obj.components if c.component_type == "Transform").properties["quaternion_xyzw"] = list(quaternion)
                candidate = candidate.model_copy(update={"objects": [*candidate.objects, obj]})
                operations.append(ScenePatchOperation(action="add_object", object_id_in_scene=identifier, object=obj))
            box = world_bounds(model, pose)
            margin = spec.region.margin_m
            if any(box[0][i] < lo[i] + margin or box[1][i] > hi[i] - margin for i in (0, 1)):
                raise ValueError("scene_layout_capacity_exceeded")
            if not facts.footprint_contains(obj, support, candidate):
                raise ValueError("scene_layout_support_invalid")
            if not rearranging and editor._overlaps(obj, candidate, clearance=spec.constraints.min_clearance_m, ignore_ids={ref.object_id}):
                raise ValueError("scene_layout_collision")
            ids.append(identifier)
        if rearranging:
            for identifier in ids:
                obj = SceneIndex(candidate).object(identifier)
                if editor._overlaps(obj, candidate, clearance=spec.constraints.min_clearance_m, ignore_ids={ref.object_id}):
                    raise ValueError("scene_layout_collision")
        patch = ScenePatch(scene_id=scene.scene_id, base_scene_version=scene.scene_version, operations=operations)
        manager.apply_patch(patch)
        if spec.pattern.kind in {"circle", "arc", "ring"}:
            assumptions = [f"layout_radius_m={radius}"]
        elif path_region:
            import json
            assumptions = ["layout_origin_bounds_xy_m=" + json.dumps([origin_low, origin_high])]
        else:
            assumptions = [f"layout_spacing_m={spacing}"]
        if len(ids) != spec.items.requested_count:
            reason = ("explicit_grid_at_least" if spec.pattern.kind in {"grid", "checker"}
                      and spec.pattern.rows is not None and spec.pattern.cols is not None
                      else "explicit_assets_at_least")
            assumptions.extend([f"layout_count_requested={spec.items.requested_count}",
                                f"layout_count_resolved={len(ids)}",
                                f"layout_count_adjustment={reason}"])
        return SceneEditResult(patch, ids, [] if rearranging else ids, assumptions=assumptions,
            adjusted_layout_spacing_m=(spacing if spec.spacing.auto and spec.pattern.kind in
                                       {"line", "grid", "checker", "alternating"} else None))

    @staticmethod
    def allocate_instance_ids(plan: LayoutPlan, *, next_object_id: int) -> list[int]:
        if next_object_id < 0:
            raise ValueError("scene_object_ids_invalid")
        return [next_object_id + index for index, _ in enumerate(plan.slots)]

    def resolve(self, spec: ArrangementSpec, plan: LayoutPlan, *, scene_id: int,
                scene_version: int, instance_ids: list[int],
                surface_bounds: tuple[tuple[float, float], tuple[float, float]] | None = None) -> LayoutResolution:
        if plan.arrangement_id != spec.arrangement_id:
            raise ValueError("scene_layout_plan_identity_mismatch")
        if len(instance_ids) != len(plan.slots):
            raise ValueError("scene_layout_instance_count_mismatch")
        bindings = {slot.slot_id: object_id for slot, object_id in zip(plan.slots, instance_ids)}
        world_positions = self.project_world_slots(plan, surface_bounds) if surface_bounds is not None else {}
        from ..planning.layout_planner import expanded_aliases
        aliases = expanded_aliases(spec)
        if len(aliases) != len(plan.slots):
            raise ValueError("scene_layout_count_conflict")
        slot_assets = {slot.slot_id: aliases[index] for index, slot in enumerate(plan.slots)}
        return LayoutResolution(arrangement_id=spec.arrangement_id, scene_id=scene_id,
                                scene_version=scene_version, instance_ids=list(instance_ids),
                                slot_bindings=bindings, slot_assets=slot_assets,
                                world_positions=world_positions)

    @staticmethod
    def project_world_slots(
        plan: LayoutPlan,
        surface_bounds: tuple[tuple[float, float], tuple[float, float]],
    ) -> dict[str, tuple[float, float]]:
        """Project normalized slots into a validated tabletop rectangle.

        This convenience projection is metadata only. Actual footprint,
        support, clearance and collision checks run in resolve_candidate;
        production evidence is read from those validated candidate transforms.
        """
        if len(surface_bounds) != 2:
            raise ValueError("scene_layout_surface_bounds_invalid")
        (xmin, ymin), (xmax, ymax) = surface_bounds
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) for value in (xmin, ymin, xmax, ymax)):
            raise ValueError("scene_layout_surface_bounds_invalid")
        if not (xmin < xmax and ymin < ymax):
            raise ValueError("scene_layout_surface_bounds_invalid")
        return {
            slot.slot_id: (xmin + slot.u * (xmax - xmin),
                           ymin + slot.v * (ymax - ymin))
            for slot in plan.slots
        }

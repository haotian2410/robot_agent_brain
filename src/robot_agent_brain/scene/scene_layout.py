from dataclasses import dataclass
import math

from .geometry import as_world, world_bounds, world_corners
from .scene_graph import WorldTransform, apply, inverse
from .layout_geometry import ContainerInteriorGeometry


@dataclass(frozen=True)
class SceneLayoutPolicy:
    """World-space initial layout only; never robot execution placement."""
    clearance_m: float = .02
    grid_size: int = 5

    def __post_init__(self):
        if not math.isfinite(self.clearance_m) or self.clearance_m < 0:
            raise ValueError("scene_layout_clearance_invalid")
        if self.grid_size < 3 or self.grid_size > 9:
            raise ValueError("scene_layout_grid_size_invalid")

    def relative_transform(self, relation, reference, reference_model, object_model, object_transform=None):
        """Return the canonical first transform for a relative relation.

        ``near`` uses the same AABB edge-clearance convention as the editor's
        candidate search.  ``on`` and ``inside`` are exposed through
        ``relative_candidates`` because they require scene/support context.
        """
        candidates = self.relative_candidates(relation, reference, reference_model, object_model,
                                               object_transform=object_transform)
        if not candidates:
            raise ValueError("unsupported_scene_layout_relation: " + str(relation))
        return candidates[0]

    def relative_candidates(self, relation, reference, reference_model, object_model, object_transform=None):
        reference = as_world(reference)
        relation = getattr(relation, "value", relation)
        planar = relation in {"left_of", "right_of", "front_of", "behind", "near"}
        if object_transform is None and planar:
            raise ValueError("scene_layout_support_transform_required")
        world = as_world(object_transform) if object_transform is not None else WorldTransform(
            (0, 0, 0), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        ref_min, ref_max = world_bounds(reference_model, reference)
        obj_min, obj_max = world_bounds(object_model, WorldTransform((0, 0, 0), world.linear))
        # Align bounding-box centers on the other axes, not model origins.
        centered = [(ref_min[i] + ref_max[i] - obj_min[i] - obj_max[i]) / 2 for i in range(3)]
        axes = {"left_of": (0, -1), "right_of": (0, 1), "front_of": (1, 1),
                "behind": (1, -1), "above": (2, 1), "below": (2, -1)}
        if relation == "near":
            # Deterministic perimeter order.  The editor filters these by
            # support, workspace and collision before committing any patch.
            candidates = []
            for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
                position = list(centered)
                position[axis] = (ref_max[axis] - obj_min[axis] + self.clearance_m
                                  if sign > 0 else ref_min[axis] - obj_max[axis] - self.clearance_m)
                position[2] = world.position[2]
                candidates.append(WorldTransform(tuple(position), world.linear))
            return candidates
        if relation not in axes:
            raise ValueError("unsupported_scene_layout_relation: " + str(relation))
        axis, sign = axes[relation]
        position = list(centered)
        position[axis] = (ref_max[axis] - obj_min[axis] + self.clearance_m if sign > 0
                          else ref_min[axis] - obj_max[axis] - self.clearance_m)
        if planar:
            position[2] = world.position[2]
        return [WorldTransform(tuple(position), world.linear)]

    def on_transform(self, reference, reference_model, object_model, object_transform=None):
        reference = as_world(reference)
        world = as_world(object_transform) if object_transform is not None else WorldTransform(
            (0, 0, 0), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        ref_min, ref_max = world_bounds(reference_model, reference)
        obj_min, obj_max = world_bounds(object_model, WorldTransform((0, 0, 0), world.linear))
        position = [(ref_min[i] + ref_max[i] - obj_min[i] - obj_max[i]) / 2 for i in range(3)]
        position[2] = ref_max[2] - obj_min[2]
        return WorldTransform(tuple(position), world.linear)

    def surface_candidates(self, reference, reference_model, object_model, object_transform=None,
                           *, region=None, center_only=False, grid_size=None, workspace_min=None,
                           workspace_max=None):
        """Deterministic 2-D candidates on a support surface.

        Candidates are generated in the reference world AABB (rather than a
        single linear offset).  The editor still proves footprint, workspace
        and collision for every candidate before accepting it.
        """
        reference = as_world(reference)
        world = as_world(object_transform) if object_transform is not None else WorldTransform(
            (0, 0, 0), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        ref_min, ref_max = world_bounds(reference_model, reference)
        obj_min, obj_max = world_bounds(object_model, WorldTransform((0, 0, 0), world.linear))
        obj_center = tuple((obj_min[i] + obj_max[i]) / 2 for i in range(3))
        half_x, half_y = (obj_max[0] - obj_min[0]) / 2, (obj_max[1] - obj_min[1]) / 2
        low_x, high_x = ref_min[0] + half_x, ref_max[0] - half_x
        low_y, high_y = ref_min[1] + half_y, ref_max[1] - half_y
        if workspace_min is not None and workspace_max is not None:
            low_x, high_x = max(low_x, workspace_min[0] + half_x), min(high_x, workspace_max[0] - half_x)
            low_y, high_y = max(low_y, workspace_min[1] + half_y), min(high_y, workspace_max[1] - half_y)
        if low_x > high_x or low_y > high_y:
            return []
        mid_x, mid_y = (ref_min[0] + ref_max[0]) / 2, (ref_min[1] + ref_max[1]) / 2
        if region in {"left_half", "left_front", "left_back"}:
            high_x = min(high_x, mid_x)
        if region in {"right_half", "right_front", "right_back"}:
            low_x = max(low_x, mid_x)
        if region in {"front_half", "left_front", "right_front"}:
            low_y = max(low_y, mid_y)
        if region in {"back_half", "left_back", "right_back"}:
            high_y = min(high_y, mid_y)
        if low_x > high_x or low_y > high_y:
            return []
        if center_only:
            points = [((low_x + high_x) / 2, (low_y + high_y) / 2)]
        else:
            # center, then a stable low-discrepancy grid.  This order keeps
            # ordinary single-object placement centered and spreads batches.
            points = []
            for fx, fy in ((.5, .5), (.25, .5), (.75, .5), (.5, .25), (.5, .75),
                           (.25, .25), (.75, .25), (.25, .75), (.75, .75),
                           (0., 0.), (1., 0.), (0., 1.), (1., 1.)):
                point = (low_x + (high_x - low_x) * fx, low_y + (high_y - low_y) * fy)
                if point not in points:
                    points.append(point)
            # Fill finer cells for dense scenes, preserving deterministic order.
            n = max(3, min(int(grid_size or self.grid_size), 9))
            for iy in range(n):
                for ix in range(n):
                    point = (low_x + (high_x - low_x) * ix / (n - 1),
                             low_y + (high_y - low_y) * iy / (n - 1))
                    if point not in points:
                        points.append(point)
        z = ref_max[2] - obj_min[2]
        return [WorldTransform((point[0] - obj_center[0], point[1] - obj_center[1], z), world.linear)
                for point in points]

    def near_candidates(self, reference, reference_model, object_model, object_transform=None):
        """Perimeter anchors followed by a local 2-D grid around each anchor."""
        base = self.relative_candidates("near", reference, reference_model, object_model, object_transform)
        result = []
        for candidate in base:
            result.append(candidate)
            for dx, dy in ((self.clearance_m, 0), (-self.clearance_m, 0), (0, self.clearance_m), (0, -self.clearance_m)):
                result.append(WorldTransform((candidate.position[0] + dx, candidate.position[1] + dy), candidate.linear))
        return result

    @staticmethod
    def inside_candidates(reference, object_model, object_transform, interior: ContainerInteriorGeometry):
        """Build center/quarter-point candidates in the verified local interior."""
        reference = as_world(reference)
        world = as_world(object_transform)
        low, high = interior.interior_aabb_min_m, interior.interior_aabb_max_m
        local_low, local_high = object_model.local_aabb_min_m, object_model.local_aabb_max_m
        object_center = tuple((local_low[i] + local_high[i]) / 2 for i in range(3))
        object_height = local_high[2] - local_low[2]
        floor_center_z = interior.floor_z_m + object_height / 2
        center = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, floor_center_z)
        points = [center]
        for x in (low[0], center[0], high[0]):
            for y in (low[1], center[1], high[1]):
                if (x, y) != (center[0], center[1]):
                    points.append((x, y, center[2]))
        object_center_world = apply(world.linear, object_center)
        return [WorldTransform(tuple(reference.point(point)[i] - object_center_world[i] for i in range(3)), world.linear)
                for point in points]

    @staticmethod
    def contained_interior(object_model, object_transform, reference, interior: ContainerInteriorGeometry, tolerance=1e-7):
        """Prove every target AABB corner lies in the verified container AABB."""
        reference = as_world(reference)
        inv = inverse(reference.linear)
        low, high = interior.interior_aabb_min_m, interior.interior_aabb_max_m
        for point in world_corners(object_model, object_transform):
            local = apply(inv, tuple(point[i] - reference.position[i] for i in range(3)))
            if any(local[i] < low[i] - tolerance or local[i] > high[i] + tolerance for i in range(3)):
                return False
        return True

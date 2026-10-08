"""Conservative world-space support geometry, not simulation or containment."""
import math

from .component_access import SceneIndex
from .geometry import local_bounds, world_bounds, world_corners
from .scene_graph import WorldTransform, world_transform, inverse, apply


class SpatialFactResolver:
    def __init__(self, assets, *, support_contact_tolerance_m=.001):
        if not math.isfinite(support_contact_tolerance_m) or support_contact_tolerance_m < 0:
            raise ValueError("support_contact_tolerance_invalid")
        self.assets = assets
        self.tolerance = support_contact_tolerance_m

    def asset(self, obj, scene):
        reference = SceneIndex(scene).metadata_ref(obj.object_id_in_scene)
        if reference is None:
            raise ValueError(f"scene_geometry_metadata_missing: {obj.object_id_in_scene}")
        return self.assets.resolve(reference)

    @staticmethod
    def bounds(model, transform):
        return world_bounds(model, transform)

    def is_surface(self, obj, scene):
        semantic = SceneIndex(scene).semantic(obj.object_id_in_scene)
        if semantic is None or semantic.category != "surface":
            return False
        linear = world_transform(scene, obj.object_id_in_scene).linear
        # Only horizontal top planes with an upright local Z are evidence.
        # This accepts world XY shear, but not tilted or inverted supports.
        return (abs(linear[2][0]) < 1e-9 and abs(linear[2][1]) < 1e-9
                and abs(linear[0][2]) < 1e-9 and abs(linear[1][2]) < 1e-9
                and linear[2][2] > 0)

    def footprint_contains(self, obj, support, scene):
        model, support_model = self.asset(obj, scene), self.asset(support, scene)
        low, high = local_bounds(support_model)
        support_world = world_transform(scene, support.object_id_in_scene)
        inverse_linear = inverse(support_world.linear)
        for point in world_corners(model, world_transform(scene, obj.object_id_in_scene)):
            local = apply(inverse_linear, tuple(point[i] - support_world.position[i] for i in range(3)))
            for axis in (0, 1):
                tolerance = self.tolerance * math.sqrt(sum(value * value for value in inverse_linear[axis]))
                if not low[axis] - tolerance <= local[axis] <= high[axis] + tolerance:
                    return False
        return True

    def infer_support(self, obj, scene):
        try:
            bottom = self.bounds(self.asset(obj, scene), world_transform(scene, obj.object_id_in_scene))[0][2]
        except (ValueError, LookupError):
            return None
        matches = []
        for support in scene.objects:
            if support.object_id_in_scene == obj.object_id_in_scene or not self.is_surface(support, scene):
                continue
            try:
                top = self.bounds(self.asset(support, scene), world_transform(scene, support.object_id_in_scene))[1][2]
                if abs(bottom - top) <= self.tolerance and self.footprint_contains(obj, support, scene):
                    matches.append(support.object_id_in_scene)
            except (ValueError, LookupError):
                continue
        return matches[0] if len(matches) == 1 else None

    def can_evaluate(self, obj, scene):
        index = SceneIndex(scene)
        surfaces = [item for item in index.semantic_objects()
                    if index.semantic(item.object_id_in_scene).category == "surface"]
        if not surfaces or any(not self.is_surface(item, scene) for item in surfaces):
            return False
        try:
            for item in [obj, *surfaces]:
                self.bounds(self.asset(item, scene), world_transform(scene, item.object_id_in_scene))
        except (ValueError, LookupError):
            return False
        return True

    def support_transform(self, model, support, scene, *, x, y, existing=None):
        """Return a WORLD placement; editor must convert it back to local."""
        if not self.is_surface(support, scene):
            raise ValueError("scene_edit_support_unknown")
        linear = existing.linear if existing is not None else ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
        origin = WorldTransform((x, y, 0), linear)
        try:
            bottom = self.bounds(model, origin)[0][2]
            top = self.bounds(self.asset(support, scene), world_transform(scene, support.object_id_in_scene))[1][2]
        except (ValueError, LookupError) as exc:
            raise ValueError("scene_edit_support_unknown") from exc
        return WorldTransform((x, y, top - bottom), linear)

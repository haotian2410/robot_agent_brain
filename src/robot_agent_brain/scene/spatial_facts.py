"""Conservative geometric support facts, not physical contact simulation.

Only horizontal, upward-facing surfaces are supported. Yaw is unrestricted;
tilted surfaces and unknown origins cannot establish evidence. No interior
geometry is available, so this module never infers container membership.
"""
from .geometry import local_bounds, rotation_matrix, world_bounds, world_corners
from ..contracts.scene import Transform


class SpatialFactResolver:
    def __init__(self, assets, *, support_contact_tolerance_m=.001):
        self.assets = assets
        self.tolerance = support_contact_tolerance_m

    def bounds(self, model, transform):
        return world_bounds(model, transform, center_origin=model.asset_id in self.assets.metadata.center_origin_assets)

    def is_surface(self, obj):
        category = self.assets.metadata.category_aliases.get(obj.category, obj.category)
        rotation = rotation_matrix(obj.transform)
        return category == "surface" and abs(rotation[2][2] - 1) < 1e-9

    def footprint_contains(self, obj, support):
        model = self.assets.get_model_property(obj.asset_id)
        support_model = self.assets.get_model_property(support.asset_id)
        low, high = local_bounds(support_model, center_origin=support.asset_id in self.assets.metadata.center_origin_assets)
        rotation = rotation_matrix(support.transform)
        corners = world_corners(model, obj.transform, center_origin=obj.asset_id in self.assets.metadata.center_origin_assets)
        for point in corners:
            # Inverse rigid transform then inverse scale: retain yaw geometry,
            # rather than accepting the empty corners of a world AABB.
            for axis in (0, 1):
                coordinate = sum(rotation[j][axis] * (point[j] - support.transform.position[j]) for j in range(3)) / support.transform.scale[axis]
                tolerance = self.tolerance / support.transform.scale[axis]
                if not low[axis] - tolerance <= coordinate <= high[axis] + tolerance:
                    return False
        return True

    def infer_support(self, obj, scene):
        try:
            bottom = self.bounds(self.assets.get_model_property(obj.asset_id), obj.transform)[0][2]
        except ValueError:
            return None
        matches = []
        for support in scene.objects:
            if support.scene_object_id == obj.scene_object_id or not self.is_surface(support):
                continue
            try:
                top = self.bounds(self.assets.get_model_property(support.asset_id), support.transform)[1][2]
                if abs(bottom - top) <= self.tolerance and self.footprint_contains(obj, support):
                    matches.append(support.scene_object_id)
            except ValueError:
                continue
        return matches[0] if len(matches) == 1 else None

    def can_evaluate(self, obj, scene):
        surfaces = [o for o in scene.objects if o.category == "surface"]
        if not surfaces or any(not self.is_surface(o) for o in surfaces):
            return False
        try:
            for item in [obj, *surfaces]:
                self.bounds(self.assets.get_model_property(item.asset_id), item.transform)
        except ValueError:
            return False
        return True

    def support_transform(self, model, support, *, x, y, existing=None):
        if not self.is_surface(support):
            raise ValueError("scene_edit_support_unknown")
        transform = (existing or Transform()).model_copy(update={"position": (x, y, 0)})
        try:
            bottom = self.bounds(model, transform)[0][2]
            top = self.bounds(self.assets.get_model_property(support.asset_id), support.transform)[1][2]
        except ValueError as exc:
            raise ValueError("scene_edit_support_unknown") from exc
        return transform.model_copy(update={"position": (x, y, top - bottom)})

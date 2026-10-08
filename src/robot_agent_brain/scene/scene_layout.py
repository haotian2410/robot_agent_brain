from dataclasses import dataclass
import math

from .geometry import as_world, world_bounds
from .scene_graph import WorldTransform


@dataclass(frozen=True)
class SceneLayoutPolicy:
    """World-space initial layout only; never robot execution placement."""
    clearance_m: float = .02

    def __post_init__(self):
        if not math.isfinite(self.clearance_m) or self.clearance_m < 0:
            raise ValueError("scene_layout_clearance_invalid")

    def relative_transform(self, relation, reference, reference_model, object_model, object_transform=None):
        reference = as_world(reference)
        planar = relation in {"left_of", "right_of", "front_of", "behind"}
        if object_transform is None and planar:
            raise ValueError("scene_layout_support_transform_required")
        world = as_world(object_transform) if object_transform is not None else WorldTransform(
            (0, 0, 0), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        ref_min, ref_max = world_bounds(reference_model, reference)
        obj_min, obj_max = world_bounds(object_model, WorldTransform((0, 0, 0), world.linear))
        # Align bounding-box centers on the other axes, not model origins.
        position = [(ref_min[i] + ref_max[i] - obj_min[i] - obj_max[i]) / 2 for i in range(3)]
        axes = {"left_of": (0, -1), "right_of": (0, 1), "front_of": (1, 1),
                "behind": (1, -1), "above": (2, 1), "below": (2, -1)}
        if relation not in axes:
            raise ValueError("unsupported_scene_layout_relation: " + relation)
        axis, sign = axes[relation]
        position[axis] = (ref_max[axis] - obj_min[axis] + self.clearance_m if sign > 0
                          else ref_min[axis] - obj_max[axis] - self.clearance_m)
        if planar:
            position[2] = world.position[2]
        return WorldTransform(tuple(position), world.linear)

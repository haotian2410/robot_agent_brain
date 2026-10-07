from __future__ import annotations

from dataclasses import dataclass
from ..contracts.scene import ModelProperty, Transform
from .geometry import world_bounds


@dataclass(frozen=True)
class SceneLayoutPolicy:
    """Deterministic initial layout only; never used for robot placement."""

    clearance_m: float = 0.02

    def relative_transform(
        self,
        relation: str,
        reference: Transform,
        reference_model: ModelProperty,
        object_model: ModelProperty,
        object_transform: Transform | None = None,
    ) -> Transform:
        rx, ry, rz = reference.position
        if object_transform is None and relation in {"left_of", "right_of", "front_of", "behind"}:
            raise ValueError("scene_layout_support_transform_required")
        object_transform = object_transform or Transform()
        # Explicit AABBs retain offset origins; dimensions-only layout keeps
        # its centered-extent convention (support inference is stricter).
        ref_min, ref_max = world_bounds(reference_model, reference, center_origin=True)
        origin_transform = object_transform.model_copy(update={"position": (0, 0, 0)})
        obj_min, obj_max = world_bounds(object_model, origin_transform, center_origin=True)
        offsets = {
            "left_of": (ref_min[0] - obj_max[0] - self.clearance_m - rx, 0.0, 0.0),
            "right_of": (ref_max[0] - obj_min[0] + self.clearance_m - rx, 0.0, 0.0),
            "front_of": (0.0, ref_max[1] - obj_min[1] + self.clearance_m - ry, 0.0),
            "behind": (0.0, ref_min[1] - obj_max[1] - self.clearance_m - ry, 0.0),
            "above": (0.0, 0.0, ref_max[2] - obj_min[2] + self.clearance_m - rz),
            "below": (0.0, 0.0, ref_min[2] - obj_max[2] - self.clearance_m - rz),
        }
        if relation not in offsets:
            raise ValueError(f"unsupported_scene_layout_relation: {relation}")
        dx, dy, dz = offsets[relation]
        z = object_transform.position[2] if relation in {"left_of", "right_of", "front_of", "behind"} else rz + dz
        return object_transform.model_copy(update={"position": (rx + dx, ry + dy, z)})

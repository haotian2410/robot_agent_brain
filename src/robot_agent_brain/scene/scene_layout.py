from __future__ import annotations

from dataclasses import dataclass
from ..contracts.scene import ModelProperty, Transform
from .geometry import world_extents


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
        object_transform = object_transform or Transform()
        ref_x, ref_y, ref_z = world_extents(reference_model.dimensions_m, reference)
        obj_x, obj_y, obj_z = world_extents(object_model.dimensions_m, object_transform)
        offsets = {
            "left_of": (-(ref_x + obj_x) / 2 - self.clearance_m, 0.0, 0.0),
            "right_of": ((ref_x + obj_x) / 2 + self.clearance_m, 0.0, 0.0),
            "front_of": (0.0, (ref_y + obj_y) / 2 + self.clearance_m, 0.0),
            "behind": (0.0, -(ref_y + obj_y) / 2 - self.clearance_m, 0.0),
            "above": (0.0, 0.0, (ref_z + obj_z) / 2 + self.clearance_m),
            "free_space": (0.0, 0.0, (ref_z + obj_z) / 2 + self.clearance_m),
        }
        if relation not in offsets:
            raise ValueError(f"unsupported_scene_layout_relation: {relation}")
        dx, dy, dz = offsets[relation]
        return object_transform.model_copy(update={"position": (rx + dx, ry + dy, rz + dz)})

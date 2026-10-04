from __future__ import annotations

from dataclasses import dataclass
from ..contracts.scene import ModelProperty, Transform


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
    ) -> Transform:
        rx, ry, rz = reference.position
        ref_x, ref_y, ref_z = reference_model.dimensions_m
        obj_x, obj_y, obj_z = object_model.dimensions_m
        offsets = {
            "left_of": (-(ref_x + obj_x) / 2 - self.clearance_m, 0.0, 0.0),
            "right_of": ((ref_x + obj_x) / 2 + self.clearance_m, 0.0, 0.0),
            "front_of": (0.0, (ref_y + obj_y) / 2 + self.clearance_m, 0.0),
            "behind": (0.0, -(ref_y + obj_y) / 2 - self.clearance_m, 0.0),
            "above": (0.0, 0.0, (ref_z + obj_z) / 2 + self.clearance_m),
        }
        if relation not in offsets:
            raise ValueError(f"unsupported_scene_layout_relation: {relation}")
        dx, dy, dz = offsets[relation]
        return Transform(position=(rx + dx, ry + dy, rz + dz))

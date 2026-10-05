from __future__ import annotations

import math
from ..contracts.scene import Transform
from .geometry import rotation_matrix


def _qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)


def translate(transform: Transform, direction: str, distance_m: float, coordinate_frame: str = "world") -> Transform:
    vectors = {
        "left": (-1, 0, 0), "right": (1, 0, 0),
        "front": (0, 1, 0), "back": (0, -1, 0),
        "up": (0, 0, 1), "down": (0, 0, -1),
    }
    if direction not in vectors:
        raise ValueError(f"unsupported_translation_direction: {direction}")
    vector = vectors[direction]
    if coordinate_frame == "object_local":
        matrix = rotation_matrix(transform)
        vector = tuple(sum(row[i] * vector[i] for i in range(3)) for row in matrix)
    vx, vy, vz = vector
    x, y, z = transform.position
    return Transform(position=(x + vx*distance_m, y + vy*distance_m, z + vz*distance_m),
                     quaternion_xyzw=transform.quaternion_xyzw, scale=transform.scale)


def rotate(transform: Transform, axis: str, angle_deg: float, coordinate_frame: str = "world") -> Transform:
    if axis not in {"x", "y", "z"}:
        raise ValueError(f"unsupported_rotation_axis: {axis}")
    half = math.radians(angle_deg) / 2
    s, c = math.sin(half), math.cos(half)
    q = {"x": (s, 0.0, 0.0, c), "y": (0.0, s, 0.0, c), "z": (0.0, 0.0, s, c)}[axis]
    current = transform.quaternion_xyzw
    value = _qmul(current, q) if coordinate_frame == "object_local" else _qmul(q, current)
    return Transform(position=transform.position, quaternion_xyzw=value, scale=transform.scale)

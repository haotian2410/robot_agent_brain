"""Semantic transform edits in WORLD space, with exact affine retention."""
import math

from .geometry import as_world
from .scene_graph import WorldTransform, multiply


def _direction(transform, vector, coordinate_frame):
    if coordinate_frame == "world":
        return vector
    if coordinate_frame != "object_local":
        raise ValueError("scene_edit_coordinate_frame_invalid")
    projected = tuple(sum(transform.linear[i][j] * vector[j] for j in range(3)) for i in range(3))
    length = math.sqrt(sum(value * value for value in projected))
    if length == 0:
        raise ValueError("scene_transform_not_invertible")
    return tuple(value / length for value in projected)


def translate(transform, direction, distance_m, coordinate_frame="world"):
    world = as_world(transform)
    vectors = {"left": (-1, 0, 0), "right": (1, 0, 0), "front": (0, 1, 0),
               "back": (0, -1, 0), "up": (0, 0, 1), "down": (0, 0, -1)}
    if direction not in vectors:
        raise ValueError("unsupported_translation_direction: " + str(direction))
    if not math.isfinite(distance_m) or distance_m <= 0:
        raise ValueError("scene_edit_distance_invalid")
    vector = _direction(world, vectors[direction], coordinate_frame)
    return WorldTransform(tuple(world.position[i] + vector[i] * distance_m for i in range(3)), world.linear)


def rotate(transform, axis, angle_deg, coordinate_frame="world"):
    world = as_world(transform)
    if axis not in {"x", "y", "z"} or not math.isfinite(angle_deg):
        raise ValueError("unsupported_rotation_axis_or_angle")
    vector = tuple(1 if i == "xyz".index(axis) else 0 for i in range(3))
    x, y, z = _direction(world, vector, coordinate_frame)
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    t = 1 - c
    rotation = ((t*x*x+c, t*x*y-s*z, t*x*z+s*y),
                (t*x*y+s*z, t*y*y+c, t*y*z-s*x),
                (t*x*z-s*y, t*y*z+s*x, t*z*z+c))
    return WorldTransform(world.position, multiply(rotation, world.linear))

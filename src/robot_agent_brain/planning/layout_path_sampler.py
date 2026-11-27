"""Bounded deterministic equal-arclength sampling in normalized space."""
import math
from bisect import bisect_right

from ..contracts.layout_path import validate_simple_path


def sample_polyline(points, count):
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("scene_layout_count_conflict")
    if not points or len(points) > 512:
        raise ValueError("scene_layout_path_invalid")
    vertices = []
    for point in points:
        if len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
            raise ValueError("scene_layout_path_out_of_range")
        vertices.append(tuple(point))
    validate_simple_path(vertices)
    if len(vertices) == 1:
        if count != 1:
            raise ValueError("scene_layout_path_degenerate")
        return vertices
    lengths = [0.]
    for a, b in zip(vertices, vertices[1:]):
        length = math.dist(a, b)
        if length <= 0:
            raise ValueError("scene_layout_path_degenerate")
        lengths.append(lengths[-1] + length)
    total = lengths[-1]
    distances = [total / 2] if count == 1 else [total * i / (count - 1) for i in range(count)]
    sampled = []
    for distance in distances:
        segment = min(bisect_right(lengths, distance) - 1, len(vertices) - 2)
        ratio = (distance - lengths[segment]) / (lengths[segment + 1] - lengths[segment])
        a, b = vertices[segment], vertices[segment + 1]
        sampled.append(tuple(a[axis] + ratio * (b[axis] - a[axis]) for axis in (0, 1)))
    return sampled

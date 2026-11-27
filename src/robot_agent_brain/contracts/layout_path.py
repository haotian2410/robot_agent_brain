"""Bounded 2-D draft-path checks; no physical collision assertions."""
from __future__ import annotations


def validate_simple_path(points):
    """Reject crossings, non-adjacent touches, and collinear backtracking.

    Input is an open polyline of distinct slots. Shared endpoints of adjacent
    segments are allowed; repeating the first slot to close a path is not.
    The caller bounds the normalized coordinates and caps the path at 512.
    """
    if len(set(points)) != len(points):
        raise ValueError("scene_layout_duplicate_slot_position")
    epsilon = 1e-12

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, p):
        return abs(cross(a, b, p)) <= epsilon and all(
            min(a[i], b[i]) - epsilon <= p[i] <= max(a[i], b[i]) + epsilon
            for i in (0, 1))

    for a, b, c in zip(points, points[1:], points[2:]):
        if abs(cross(a, b, c)) <= epsilon:
            dot = sum((b[i] - a[i]) * (c[i] - b[i]) for i in (0, 1))
            if dot < -epsilon:
                raise ValueError("scene_layout_path_self_intersection")
    segments = list(zip(points, points[1:]))
    for i, (a, b) in enumerate(segments):
        for c, d in segments[i + 2:]:
            ab_c, ab_d = cross(a, b, c), cross(a, b, d)
            cd_a, cd_b = cross(c, d, a), cross(c, d, b)
            opposite_ab = (ab_c > epsilon and ab_d < -epsilon) or (ab_c < -epsilon and ab_d > epsilon)
            opposite_cd = (cd_a > epsilon and cd_b < -epsilon) or (cd_a < -epsilon and cd_b > epsilon)
            if ((opposite_ab and opposite_cd) or on_segment(a, b, c) or on_segment(a, b, d)
                    or on_segment(c, d, a) or on_segment(c, d, b)):
                raise ValueError("scene_layout_path_self_intersection")

from ..contracts.scene import Transform
from itertools import product


def rotation_matrix(transform: Transform):
    x, y, z, w = transform.quaternion_xyzw
    return (
        (1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
        (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
        (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)),
    )


def world_extents(dimensions, transform):
    matrix = rotation_matrix(transform)
    return tuple(sum(abs(matrix[row][col]) * dimensions[col] * transform.scale[col]
                     for col in range(3)) for row in range(3))


def local_bounds(model, *, center_origin=False):
    if model.aabb_m is not None:
        return model.aabb_m[:3], model.aabb_m[3:]
    if not center_origin:
        raise ValueError("scene_geometry_origin_unknown: " + model.asset_id)
    return tuple(-d / 2 for d in model.dimensions_m), tuple(d / 2 for d in model.dimensions_m)


def world_corners(model, transform, *, center_origin=False):
    low, high = local_bounds(model, center_origin=center_origin)
    rotation = rotation_matrix(transform)
    return [tuple(transform.position[i] + sum(rotation[i][j] * corner[j] * transform.scale[j]
                                             for j in range(3)) for i in range(3))
            for corner in product(*zip(low, high))]


def world_bounds(model, transform, *, center_origin=False):
    corners = world_corners(model, transform, center_origin=center_origin)
    return (tuple(min(p[i] for p in corners) for i in range(3)),
            tuple(max(p[i] for p in corners) for i in range(3)))


def world_bottom_z(model, transform, *, center_origin=False):
    return world_bounds(model, transform, center_origin=center_origin)[0][2]


def world_top_z(model, transform, *, center_origin=False):
    return world_bounds(model, transform, center_origin=center_origin)[1][2]

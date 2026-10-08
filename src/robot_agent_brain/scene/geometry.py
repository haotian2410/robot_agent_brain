"""Full local AABB geometry transformed by an exact world affine matrix."""
from itertools import product

from .scene_graph import WorldTransform, quaternion_matrix


def rotation_matrix(transform):
    """Rotation for explicit TRS operations, not world bounds with shear."""
    return quaternion_matrix(transform.quaternion_xyzw)


def as_world(transform):
    if isinstance(transform, WorldTransform):
        return transform
    if transform.parent is not None:
        raise ValueError("scene_geometry_requires_world_transform")
    return WorldTransform.from_local(transform)


def world_extents(dimensions, transform):
    matrix = as_world(transform).linear
    return tuple(sum(abs(matrix[row][column]) * dimensions[column] for column in range(3))
                 for row in range(3))


def local_bounds(model):
    return model.local_aabb_min_m, model.local_aabb_max_m


def world_corners(model, transform):
    low, high = local_bounds(model)
    world = as_world(transform)
    return [world.point(corner) for corner in product(*zip(low, high))]


def world_bounds(model, transform):
    corners = world_corners(model, transform)
    return (tuple(min(point[i] for point in corners) for i in range(3)),
            tuple(max(point[i] for point in corners) for i in range(3)))


def world_bottom_z(model, transform):
    return world_bounds(model, transform)[0][2]


def world_top_z(model, transform):
    return world_bounds(model, transform)[1][2]

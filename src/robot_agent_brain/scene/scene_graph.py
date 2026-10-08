"""Exact affine world transforms, with explicit failure for non-TRS edits.

Nonuniformly scaled/rotated parent chains can produce shear. Spatial queries
retain the full linear matrix instead of approximating it as quaternion+scale.
An edited local matrix must be representable by the shared Transform contract.
"""
from dataclasses import dataclass
import math

from ..contracts.scene import TransformProperties
from .component_access import SceneIndex


def multiply(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def apply(matrix, vector):
    return tuple(sum(row[i] * vector[i] for i in range(3)) for row in matrix)


def inverse(matrix):
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e*i-f*h) - b * (d*i-f*g) + c * (d*h-e*g)
    if determinant == 0 or not math.isfinite(determinant):
        raise ValueError("scene_transform_not_invertible")
    cofactors = ((e*i-f*h, c*h-b*i, b*f-c*e), (f*g-d*i, a*i-c*g, c*d-a*f),
                 (d*h-e*g, b*g-a*h, a*e-b*d))
    return tuple(tuple(v / determinant for v in row) for row in cofactors)


def quaternion_matrix(q):
    x, y, z, w = q
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def matrix_quaternion(m):
    trace = sum(m[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = ((m[2][1]-m[1][2])/s, (m[0][2]-m[2][0])/s, (m[1][0]-m[0][1])/s, s/4)
    else:
        i = max(range(3), key=lambda axis: m[axis][axis])
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(max(0, 1 + m[i][i] - m[j][j] - m[k][k])) * 2
        q = [0., 0., 0., (m[k][j] - m[j][k]) / s]
        q[i], q[j], q[k] = s / 4, (m[j][i] + m[i][j]) / s, (m[k][i] + m[i][k]) / s
    norm = math.sqrt(sum(v*v for v in q))
    return tuple(v / norm for v in q)


@dataclass(frozen=True)
class WorldTransform:
    position: tuple[float, float, float]
    linear: tuple[tuple[float, float, float], ...]

    @classmethod
    def from_local(cls, transform):
        rotation = quaternion_matrix(transform.quaternion_xyzw)
        return cls(tuple(transform.position), tuple(tuple(rotation[i][j] * transform.scale[j]
                   for j in range(3)) for i in range(3)))

    def point(self, local_point):
        offset = apply(self.linear, local_point)
        return tuple(a + b for a, b in zip(self.position, offset))

    @property
    def scale(self):
        return tuple(math.sqrt(sum(self.linear[i][j] ** 2 for i in range(3))) for j in range(3))

    def to_local_properties(self, parent=None):
        scale = self.scale
        if any(v <= 0 or not math.isfinite(v) for v in scale):
            raise ValueError("scene_transform_invalid_scale")
        rotation = tuple(tuple(self.linear[i][j] / scale[j] for j in range(3)) for i in range(3))
        for i in range(3):
            for j in range(3):
                dot = sum(rotation[k][i] * rotation[k][j] for k in range(3))
                if not math.isclose(dot, float(i == j), abs_tol=1e-8):
                    raise ValueError("scene_edit_nonrepresentable_local_shear")
        return TransformProperties(position=self.position, quaternion_xyzw=matrix_quaternion(rotation), scale=scale, parent=parent)


def world_transform(scene, object_id):
    index = SceneIndex(scene)
    chain, visited, identifier = [], set(), object_id
    while identifier is not None:
        if identifier in visited:
            raise ValueError("scene_parent_cycle")
        visited.add(identifier)
        transform = index.transform(identifier)
        chain.append(transform)
        identifier = transform.parent
    world = WorldTransform((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
    for transform in reversed(chain):
        local = WorldTransform.from_local(transform)
        world = WorldTransform(world.point(local.position), multiply(world.linear, local.linear))
    return world


def local_from_world(scene, object_id, transform):
    if not isinstance(transform, WorldTransform):
        transform = WorldTransform.from_local(transform)
    parent = SceneIndex(scene).transform(object_id).parent
    if parent is None:
        return transform.to_local_properties()
    parent_world = world_transform(scene, parent)
    inverse_parent = inverse(parent_world.linear)
    local = WorldTransform(apply(inverse_parent, tuple(a-b for a, b in zip(transform.position, parent_world.position))),
                           multiply(inverse_parent, transform.linear))
    return local.to_local_properties(parent=parent)

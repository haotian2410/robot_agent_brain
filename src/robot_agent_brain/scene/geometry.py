from ..contracts.scene import Transform


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

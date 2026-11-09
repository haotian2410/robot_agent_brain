"""Axis-based target poses and minimal horizontal support fitting."""
from .geometry import local_bounds, world_bounds, world_corners
from .scene_graph import WorldTransform, inverse, apply


def fit_support(model, pose, support_model, support_pose):
    # A world-Z contact is only meaningful for a horizontal upright support.
    m = support_pose.linear
    if any(abs(m[i][j]) > 1e-9 for i, j in ((2, 0), (2, 1), (0, 2), (1, 2))) or m[2][2] <= 0:
        raise ValueError("scene_edit_support_unknown")
    inv = inverse(m)
    low, high = local_bounds(support_model)
    corners = [apply(inv, tuple(p[i] - support_pose.position[i] for i in range(3)))
               for p in world_corners(model, pose)]
    delta = [0., 0., 0.]
    for axis in (0, 1):
        bottom = min(p[axis] for p in corners)
        top = max(p[axis] for p in corners)
        if top - bottom > high[axis] - low[axis] + 1e-9:
            raise ValueError("scene_edit_support_footprint_exceeded")
        delta[axis] = max(low[axis] - bottom, min(0., high[axis] - top))
    shift = apply(m, delta)
    position = tuple(pose.position[i] + shift[i] for i in range(3))
    contact = world_bounds(support_model, support_pose)[1][2] - world_bounds(model, pose)[0][2]
    return WorldTransform((position[0], position[1], position[2] + contact), pose.linear)


def posture_transform(model, world, posture):
    # Refuse to erase shear; axis dimensions include the current instance scale.
    scale = world.to_local_properties().scale
    low, high = local_bounds(model)
    lengths = [(high[i] - low[i]) * scale[i] for i in range(3)]
    vertical = (min if posture == "flat" else max)(range(3), key=lambda i: lengths[i])
    remaining = [i for i in range(3) if i != vertical]
    horizontal = max(remaining, key=lambda i: lengths[i])
    other = next(i for i in remaining if i != horizontal)
    columns = {horizontal: (1., 0., 0.), other: (0., 1., 0.), vertical: (0., 0., 1.)}
    matrix = tuple(tuple(columns[j][i] for j in range(3)) for i in range(3))
    a, b, c = matrix
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if determinant < 0:
        columns[other] = (0., -1., 0.)
    linear = tuple(tuple(columns[j][i] * scale[j] for j in range(3)) for i in range(3))
    return WorldTransform(world.position, linear)

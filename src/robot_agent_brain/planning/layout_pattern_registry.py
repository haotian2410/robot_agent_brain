"""Deterministic normalized pattern generators for ArrangementSpec."""
from __future__ import annotations

import math
from collections.abc import Callable
from ..contracts.arrangement import ArrangementSpec


def _line(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    axis = spec.pattern.axis or "x"
    if count == 1:
        values = [0.5]
    else:
        values = [i / (count - 1) for i in range(count)]
    return [(value, 0.5) if axis == "x" else (0.5, value) for value in values]


def grid_cells(spec: ArrangementSpec, count: int):
    """Shared cell order for coordinates and checker asset assignments."""
    rows = spec.pattern.rows
    cols = spec.pattern.cols
    if rows is None and cols is None:
        cols = max(1, math.ceil(math.sqrt(count)))
        rows = math.ceil(count / cols)
    elif rows is None:
        rows = math.ceil(count / cols)
    elif cols is None:
        cols = math.ceil(count / rows)
    if rows * cols < count:
        raise ValueError("scene_layout_count_conflict")
    cells = ([(r, c) for c in range(cols) for r in range(rows)]
             if spec.pattern.order == "column_major" else
             [(r, c) for r in range(rows) for c in range(cols)])
    return rows, cols, cells[:count]


def _grid(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    rows, cols, cells = grid_cells(spec, count)
    points = []
    for r, c in cells:
        u = 0.5 if cols == 1 else c / (cols - 1)
        v = 0.5 if rows == 1 else r / (rows - 1)
        points.append((u, v))
    return points


def _circle(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    # Radius is a physical hint; normalized slots stay inside the declared region.
    direction = -1 if spec.pattern.order == "clockwise" else 1
    return [(0.5 + 0.45 * math.cos(direction * 2 * math.pi * i / count),
             0.5 + 0.45 * math.sin(direction * 2 * math.pi * i / count)) for i in range(count)]


def _ring(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    return _circle(spec, count)


def _arc(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    span = math.radians(spec.pattern.angle_span_deg or 180.0)
    direction = -1 if spec.pattern.order == "clockwise" else 1
    start = -direction * span / 2
    denominator = count if spec.pattern.angle_span_deg == 360 else max(1, count - 1)
    angles = [0.] if count == 1 else [start + direction * span * i / denominator for i in range(count)]
    return [(0.5 + 0.45 * math.cos(angle), 0.5 + 0.45 * math.sin(angle)) for angle in angles]


def _checker(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    return _grid(spec, count)


def _scatter(spec: ArrangementSpec, count: int) -> list[tuple[float, float]]:
    import random
    rng = random.Random(spec.seed if spec.seed is not None else 0)
    points = []
    for _ in range(count * 100):
        candidate = (round(rng.uniform(0.05, 0.95), 8), round(rng.uniform(0.05, 0.95), 8))
        if all((candidate[0] - u) ** 2 + (candidate[1] - v) ** 2 >= 0.01 ** 2 for u, v in points):
            points.append(candidate)
            if len(points) == count:
                return points
    raise ValueError("scene_layout_capacity_exceeded")


PATTERN_GENERATORS: dict[str, Callable[[ArrangementSpec, int], list[tuple[float, float]]]] = {
    "line": _line, "grid": _grid, "circle": _circle, "ring": _ring,
    "arc": _arc, "checker": _checker, "alternating": _line, "scatter": _scatter,
}


def supported_pattern(kind: str) -> bool:
    return kind in PATTERN_GENERATORS or kind in {"text", "custom"}

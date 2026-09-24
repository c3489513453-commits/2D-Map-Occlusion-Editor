from __future__ import annotations

import numpy as np


def _point_segment_distance(point, start, end) -> float:
    point = np.asarray(point, dtype=float)
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    direction = end - start
    length_squared = float(direction @ direction)
    if length_squared == 0:
        return float(np.linalg.norm(point - start))
    amount = max(0.0, min(1.0, float((point - start) @ direction) / length_squared))
    return float(np.linalg.norm(point - (start + amount * direction)))


def _simplify(points: list[list[int]], tolerance: float) -> list[list[int]]:
    if len(points) <= 2 or tolerance <= 0:
        return points
    distance, index = max(
        (_point_segment_distance(point, points[0], points[-1]), index)
        for index, point in enumerate(points[1:-1], 1)
    )
    if distance <= tolerance:
        return [points[0], points[-1]]
    return _simplify(points[:index + 1], tolerance)[:-1] + _simplify(points[index:], tolerance)


def baseline_lines_from_mask(mask: np.ndarray, simplify_tolerance: float = 1.5) -> list[list[list[int]]]:
    """Return bottom-most opaque pixels as simplified, gap-separated polylines."""
    pixels = np.asarray(mask) > 0
    if pixels.ndim != 2:
        raise ValueError("蒙版必须是二维图像")
    occupied_columns = np.flatnonzero(pixels.any(axis=0))
    if not len(occupied_columns):
        return []
    lines: list[list[list[int]]] = []
    current: list[list[int]] = []
    previous_x = None
    for x in occupied_columns:
        if previous_x is not None and x != previous_x + 1:
            if len(current) >= 2:
                lines.append(_simplify(current, simplify_tolerance))
            current = []
        y = int(np.flatnonzero(pixels[:, x])[-1])
        current.append([int(x), y])
        previous_x = int(x)
    if len(current) >= 2:
        lines.append(_simplify(current, simplify_tolerance))
    return lines


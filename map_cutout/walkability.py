from __future__ import annotations

import math

import numpy as np


def adaptive_walkable_boundary(mask: np.ndarray) -> list[list[float]]:
    kept = np.asarray(mask, dtype=bool)
    ys, xs = np.nonzero(kept)
    if not len(xs):
        return []
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max()) + 1
    width = right - left + 1
    height = bottom - top
    if width < 2 or height < 2:
        return []
    obstacle_height = max(height * .10, min(height * .30, width * .50))
    boundary_y = float(bottom - obstacle_height)
    return [[float(left), boundary_y], [float(right), boundary_y]]


def _boundary_by_x(lines: list[list[list[float]]], width: int) -> np.ndarray:
    result = np.full(width, np.nan, dtype=np.float64)
    if not lines or len(lines[0]) < 2:
        return result
    points = lines[0]
    for start, end in zip(points, points[1:]):
        x1, y1 = float(start[0]), float(start[1])
        x2, y2 = float(end[0]), float(end[1])
        if x1 == x2:
            column = int(round(x1))
            if 0 <= column < width:
                result[column] = min(y1, y2)
            continue
        lo = max(0, int(math.ceil(min(x1, x2))))
        hi = min(width - 1, int(math.floor(max(x1, x2))))
        for x in range(lo, hi + 1):
            ratio = (x - x1) / (x2 - x1)
            result[x] = y1 + (y2 - y1) * ratio
    return result


def resource_walkable_and_obstacle(
    mask: np.ndarray,
    lines: list[list[list[float]]],
) -> tuple[np.ndarray, np.ndarray]:
    resource = np.asarray(mask, dtype=bool)
    boundaries = _boundary_by_x(lines, resource.shape[1])
    yy = np.arange(resource.shape[0], dtype=np.float64)[:, None]
    covered = np.isfinite(boundaries)[None, :]
    passable = resource & covered & (yy < boundaries[None, :])
    return passable, resource & ~passable


def compose_final_walkable(
    manual_masks: list[np.ndarray],
    resources: list[tuple[np.ndarray, list[list[list[float]]]]],
) -> np.ndarray:
    arrays = [np.asarray(mask, dtype=bool) for mask in manual_masks]
    arrays.extend(np.asarray(mask, dtype=bool) for mask, _ in resources)
    if not arrays:
        raise ValueError("没有可用于计算行走区域的蒙版")
    shape = arrays[0].shape
    if any(mask.shape != shape for mask in arrays):
        raise ValueError("蒙版尺寸必须一致")
    manual = np.zeros(shape, dtype=bool)
    for mask in manual_masks:
        manual |= np.asarray(mask, dtype=bool)
    resource_union = np.zeros(shape, dtype=bool)
    passable_union = np.zeros(shape, dtype=bool)
    obstacle_union = np.zeros(shape, dtype=bool)
    for mask, lines in resources:
        resource = np.asarray(mask, dtype=bool)
        resource_union |= resource
        passable, obstacle = resource_walkable_and_obstacle(resource, lines)
        passable_union |= passable
        obstacle_union |= obstacle
    candidates = (manual & ~resource_union) | passable_union
    return candidates & ~obstacle_union

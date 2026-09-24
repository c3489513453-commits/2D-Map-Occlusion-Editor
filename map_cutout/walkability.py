from __future__ import annotations

import math

import numpy as np


def _simplify_collinear(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for previous, current, following in zip(points, points[1:], points[2:]):
        left = (current[1] - previous[1]) * (following[0] - current[0])
        right = (following[1] - current[1]) * (current[0] - previous[0])
        if abs(left - right) > 1e-7:
            kept.append(current)
    kept.append(points[-1])
    return kept


def adaptive_walkable_boundaries(mask: np.ndarray) -> list[list[list[float]]]:
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
    occupied_columns = np.flatnonzero(kept.any(axis=0))
    runs: list[list[int]] = []
    for column in occupied_columns:
        if not runs or column != runs[-1][-1] + 1:
            runs.append([int(column)])
        else:
            runs[-1].append(int(column))
    lines = []
    for run in runs:
        if len(run) < 2:
            continue
        bottoms = np.array([
            np.flatnonzero(kept[:, column])[-1] + 1 for column in run
        ], dtype=np.float64)
        window = min(31, max(3, (len(run) // 20) * 2 + 1))
        radius = window // 2
        smoothed = np.array([
            np.median(bottoms[max(0, index - radius):index + radius + 1])
            for index in range(len(run))
        ])
        points = []
        for column, local_bottom in zip(run, smoothed):
            column_pixels = np.flatnonzero(kept[:, column])
            target = local_bottom - obstacle_height
            row = int(column_pixels[np.argmin(np.abs(column_pixels - target))])
            points.append([float(column), float(row)])
        lines.append(_simplify_collinear(points))
    return lines


def adaptive_walkable_boundary(mask: np.ndarray) -> list[list[float]]:
    lines = adaptive_walkable_boundaries(mask)
    return lines[0] if lines else []


def _line_boundary_by_x(points: list[list[float]], width: int) -> np.ndarray:
    result = np.full(width, np.nan, dtype=np.float64)
    if len(points) < 2:
        return result
    for start, end in zip(points, points[1:]):
        x1, y1 = float(start[0]), float(start[1])
        x2, y2 = float(end[0]), float(end[1])
        if x1 == x2:
            column = int(round(x1))
            if 0 <= column < width:
                value = min(y1, y2)
                result[column] = value if np.isnan(result[column]) else min(result[column], value)
            continue
        lo = max(0, int(math.ceil(min(x1, x2))))
        hi = min(width - 1, int(math.floor(max(x1, x2))))
        for x in range(lo, hi + 1):
            ratio = (x - x1) / (x2 - x1)
            value = y1 + (y2 - y1) * ratio
            result[x] = value if np.isnan(result[x]) else min(result[x], value)
    return result


def _has_side_closures(points: list[list[float]]) -> bool:
    if len(points) < 4:
        return False
    segments = ((points[0], points[1]), (points[-2], points[-1]))
    vertical = all(
        abs(float(end[0]) - float(start[0]))
        <= max(2.0, abs(float(end[1]) - float(start[1])) * .10)
        and abs(float(end[1]) - float(start[1])) >= 2.0
        for start, end in segments
    )
    return vertical and float(points[0][1]) > float(points[1][1]) \
        and float(points[-1][1]) > float(points[-2][1])


def resource_walkable_and_obstacle(
    mask: np.ndarray,
    lines: list[list[list[float]]],
) -> tuple[np.ndarray, np.ndarray]:
    resource = np.asarray(mask, dtype=bool)
    yy = np.arange(resource.shape[0], dtype=np.float64)[:, None]
    closed_lines = [line for line in lines if _has_side_closures(line)]
    if closed_lines:
        obstacle = np.zeros_like(resource)
        for line in closed_lines:
            boundaries = _line_boundary_by_x(line, resource.shape[1])
            covered = np.isfinite(boundaries)[None, :]
            obstacle |= resource & covered & (yy >= boundaries[None, :])
        return resource & ~obstacle, obstacle
    passable = np.zeros_like(resource)
    for line in lines:
        boundaries = _line_boundary_by_x(line, resource.shape[1])
        covered = np.isfinite(boundaries)[None, :]
        passable |= resource & covered & (yy < boundaries[None, :])
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

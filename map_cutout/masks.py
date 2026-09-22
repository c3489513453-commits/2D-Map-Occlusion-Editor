from __future__ import annotations

import math

import numpy as np

from .domain import BoundingBox


class EmptyMaskError(ValueError):
    pass


def take_unoccupied(mask: np.ndarray, occupied: np.ndarray) -> np.ndarray:
    """Keep only the pixels that no earlier mask has already claimed."""
    incoming = np.asarray(mask, dtype=bool)
    claimed = np.asarray(occupied, dtype=bool)
    if incoming.shape != claimed.shape:
        raise ValueError("蒙版尺寸必须一致")
    return incoming & ~claimed


def union_masks(masks: list[np.ndarray]) -> np.ndarray:
    if not masks:
        raise EmptyMaskError("没有可以合并的蒙版")
    shape = masks[0].shape
    if any(mask.shape != shape for mask in masks):
        raise ValueError("蒙版尺寸必须一致")
    return np.maximum.reduce([mask.astype(np.uint8) for mask in masks])


def paint_circle(
    mask: np.ndarray, x: float, y: float, radius: float, value: int
) -> np.ndarray:
    result = mask.astype(np.uint8, copy=True)
    height, width = result.shape
    x1 = max(0, int(np.floor(x - radius)))
    y1 = max(0, int(np.floor(y - radius)))
    x2 = min(width, int(np.ceil(x + radius)) + 1)
    y2 = min(height, int(np.ceil(y + radius)) + 1)
    yy, xx = np.ogrid[y1:y2, x1:x2]
    circle = (xx - x) ** 2 + (yy - y) ** 2 <= radius**2
    patch = result[y1:y2, x1:x2]
    patch[circle] = np.uint8(value)
    return result


def _nonzero_polygon(points: list[tuple[float, float]], height: int, width: int) -> np.ndarray:
    """Pixels whose center sits inside the polygon, including where the line crosses itself.

    The on-screen lasso uses this same rule. A crossing outline used to be saved
    with the middle left empty, so the area disappeared after leaving the map.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    events_x: list[list[int]] = [[] for _ in range(height)]
    events_sign: list[list[int]] = [[] for _ in range(height)]
    count = len(pts)
    for index in range(count):
        x1, y1 = float(pts[index, 0]), float(pts[index, 1])
        x2, y2 = float(pts[(index + 1) % count, 0]), float(pts[(index + 1) % count, 1])
        if y1 == y2:
            continue
        sign = 1 if y2 > y1 else -1
        y_lo, y_hi = (y1, y2) if y1 < y2 else (y2, y1)
        row0 = max(0, int(math.ceil(y_lo - 1e-9)))
        row1 = min(height, int(math.ceil(y_hi - 1e-9)))
        for y in range(row0, row1):
            yc = y + 0.5
            if not (y_lo <= yc < y_hi):
                continue
            x = x1 + (yc - y1) * (x2 - x1) / (y2 - y1)
            events_x[y].append(int(math.floor(x - 0.5)) + 1)
            events_sign[y].append(sign)
    covered = np.zeros((height, width), dtype=bool)
    for y in range(height):
        if not events_x[y]:
            continue
        cols = np.asarray(events_x[y], dtype=np.int32)
        signs = np.asarray(events_sign[y], dtype=np.int16)
        delta = np.zeros(width, dtype=np.int16)
        before = cols < 0
        if before.any():
            delta[0] += np.int16(signs[before].sum())
        on_row = (cols >= 0) & (cols < width)
        if on_row.any():
            np.add.at(delta, cols[on_row], signs[on_row])
        covered[y] = np.cumsum(delta) != 0
    return covered


def paint_polygon(
    mask: np.ndarray, points: list[tuple[float, float]], value: int
) -> np.ndarray:
    if len(points) < 3:
        raise ValueError("套索至少需要三个点")
    result = np.asarray(mask).astype(np.uint8, copy=True)
    result[_nonzero_polygon(points, result.shape[0], result.shape[1])] = np.uint8(value)
    return result


def to_mask_image(mask: np.ndarray) -> np.ndarray:
    """Store a mask as a grayscale PNG: 0 is outside, 255 is kept.

    Boolean masks load back as 0/1. Painting then writes 255 into the new
    region. Multiplying that 255 by 255 overflows and becomes almost black,
    so the edit looks like it did nothing.
    """
    kept = (np.asarray(mask) > 0).astype(np.uint8)
    return kept * np.uint8(255)


def mask_bounds(mask: np.ndarray) -> BoundingBox:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise EmptyMaskError("蒙版为空，无法导出")
    return BoundingBox(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

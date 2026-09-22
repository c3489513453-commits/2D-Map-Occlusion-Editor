from __future__ import annotations

import numpy as np

from .domain import BoundingBox


class EmptyMaskError(ValueError):
    pass


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


def mask_bounds(mask: np.ndarray) -> BoundingBox:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise EmptyMaskError("蒙版为空，无法导出")
    return BoundingBox(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

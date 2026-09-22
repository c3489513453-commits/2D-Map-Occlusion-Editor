from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

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


def paint_polygon(
    mask: np.ndarray, points: list[tuple[float, float]], value: int
) -> np.ndarray:
    if len(points) < 3:
        raise ValueError("套索至少需要三个点")
    image = Image.fromarray(mask.astype(np.uint8, copy=True), mode="L")
    ImageDraw.Draw(image).polygon(points, fill=int(value))
    return np.asarray(image, dtype=np.uint8).copy()


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

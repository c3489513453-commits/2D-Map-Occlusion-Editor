import math

import numpy as np
import pytest

from map_cutout.domain import BoundingBox
from map_cutout.masks import (
    EmptyMaskError,
    mask_bounds,
    paint_circle,
    paint_polygon,
    take_unoccupied,
    to_mask_image,
    union_masks,
)


def test_later_mask_keeps_only_the_unclaimed_pixels():
    occupied = np.zeros((4, 6), dtype=bool)
    occupied[:, :3] = True
    incoming = np.ones((4, 6), dtype=bool)
    fresh = take_unoccupied(incoming, occupied)
    assert fresh[:, :3].sum() == 0
    assert fresh[:, 3:].all()
    assert occupied[:, :3].all()


def test_paint_and_erase_are_clipped_to_image_bounds():
    mask = np.zeros((10, 10), dtype=np.uint8)
    painted = paint_circle(mask, x=0, y=0, radius=3, value=255)
    erased = paint_circle(painted, x=0, y=0, radius=1, value=0)
    assert painted.shape == (10, 10)
    assert painted[0, 0] == 255
    assert erased[0, 0] == 0


def test_union_and_bounds_use_exclusive_bottom_right():
    first = np.zeros((8, 10), dtype=np.uint8)
    second = first.copy()
    first[1:3, 2:4] = 255
    second[4:6, 6:8] = 255
    merged = union_masks([first, second])
    assert mask_bounds(merged) == BoundingBox(2, 1, 8, 6)


def test_empty_mask_has_explicit_error():
    with pytest.raises(EmptyMaskError):
        mask_bounds(np.zeros((3, 3), dtype=np.uint8))


def test_polygon_can_add_and_remove_a_closed_region():
    mask = np.zeros((12, 12), dtype=np.uint8)
    added = paint_polygon(mask, [(2, 2), (9, 2), (9, 9), (2, 9)], 255)
    removed = paint_polygon(added, [(4, 4), (7, 4), (7, 7), (4, 7)], 0)

    assert added[3, 3] == 255
    assert added[0, 0] == 0
    assert removed[5, 5] == 0
    assert removed[3, 3] == 255


def test_crossed_lasso_keeps_the_middle():
    points = []
    for index in range(5):
        angle = -math.pi / 2 + index * 4 * math.pi / 5
        points.append((50 + 40 * math.cos(angle), 50 + 40 * math.sin(angle)))
    painted = paint_polygon(np.zeros((100, 100), dtype=np.uint8), points, 255)
    assert painted[50, 50] == 255
    assert painted[0, 0] == 0


def test_painted_white_pixels_stay_white_when_saved():
    mask = np.zeros((8, 8), dtype=np.uint8)
    mask[1:3, 1:3] = 1
    painted = paint_polygon(mask, [(4, 1), (7, 1), (7, 4), (4, 4)], 255)
    image = to_mask_image(painted)

    assert image[2, 2] == 255
    assert image[2, 5] == 255
    assert image[0, 0] == 0
    assert int(image.max()) == 255

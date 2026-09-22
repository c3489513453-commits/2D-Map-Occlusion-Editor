import numpy as np
import pytest

from map_cutout.domain import BoundingBox
from map_cutout.masks import EmptyMaskError, mask_bounds, paint_circle, union_masks


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

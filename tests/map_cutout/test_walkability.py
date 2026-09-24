import numpy as np

from map_cutout.walkability import (
    adaptive_walkable_boundary,
    adaptive_walkable_boundaries,
    compose_final_walkable,
    resource_walkable_and_obstacle,
)


def test_adaptive_boundary_uses_thirty_percent_for_square_resource():
    mask = np.ones((20, 20), dtype=bool)

    assert adaptive_walkable_boundary(mask) == [[0.0, 14.0], [19.0, 14.0]]


def test_adaptive_boundary_caps_tall_thin_resource_by_width():
    mask = np.zeros((100, 20), dtype=bool)
    mask[:, 5:15] = True

    assert adaptive_walkable_boundary(mask) == [[5.0, 90.0], [14.0, 90.0]]


def test_empty_and_single_pixel_masks_do_not_create_invalid_lines():
    empty = np.zeros((8, 8), dtype=bool)
    single = empty.copy(); single[4, 3] = True

    assert adaptive_walkable_boundary(empty) == []
    assert adaptive_walkable_boundary(single) == []


def test_adaptive_boundaries_follow_bottom_contour_instead_of_cutting_straight_across():
    mask = np.zeros((20, 14), dtype=bool)
    mask[2:18, 1:6] = True
    mask[2:11, 6:13] = True

    lines = adaptive_walkable_boundaries(mask)

    assert len(lines) == 1
    by_x = {int(x): y for x, y in lines[0]}
    assert by_x[1] > by_x[12]
    assert all(mask[int(y), x] for x, y in by_x.items())


def test_adaptive_boundaries_split_at_empty_columns():
    mask = np.zeros((12, 14), dtype=bool)
    mask[2:10, 1:5] = True
    mask[3:11, 8:13] = True

    lines = adaptive_walkable_boundaries(mask)

    assert len(lines) == 2
    assert max(point[0] for point in lines[0]) < min(point[0] for point in lines[1])


def test_short_boundary_leaves_uncovered_resource_pixels_blocked():
    mask = np.ones((10, 10), dtype=bool)
    passable, obstacle = resource_walkable_and_obstacle(
        mask, [[[3, 6], [6, 6]]])

    assert passable[2, 4]
    assert obstacle[8, 4]
    assert obstacle[2, 1]
    assert not passable[2, 1]


def test_overlapping_resource_obstacle_wins_over_other_resource_passable():
    manual = np.ones((10, 10), dtype=bool)
    resource_a = np.zeros_like(manual); resource_a[:, 2:8] = True
    resource_b = np.zeros_like(manual); resource_b[4:9, 4:6] = True

    final = compose_final_walkable(
        [manual],
        [
            (resource_a, [[[2, 8], [7, 8]]]),
            (resource_b, [[[4, 5], [5, 5]]]),
        ],
    )

    assert final[3, 4]
    assert not final[6, 4]
    assert final[1, 0]


def test_resource_without_boundary_is_entirely_obstacle():
    manual = np.ones((5, 5), dtype=bool)
    resource = np.zeros_like(manual); resource[1:4, 1:4] = True

    final = compose_final_walkable([manual], [(resource, [])])

    assert final[0, 0]
    assert not final[2, 2]

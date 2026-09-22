import numpy as np
from PIL import Image

from map_cutout.domain import ExportMode
from map_cutout.exporter import export_layer, unique_windows_name


def rectangular_mask(size, box):
    width, height = size
    mask = np.zeros((height, width), dtype=np.uint8)
    x1, y1, x2, y2 = box
    mask[y1:y2, x1:x2] = 255
    return mask


def test_tight_and_full_size_exports_have_expected_dimensions(tmp_path):
    image = Image.new("RGBA", (10, 8), "red")
    mask = rectangular_mask((10, 8), (2, 1, 7, 6))
    tight = export_layer(image, mask, tmp_path / "tight.png", ExportMode.TIGHT)
    full = export_layer(image, mask, tmp_path / "full.png", ExportMode.FULL_SIZE)
    assert Image.open(tight).size == (5, 5)
    assert Image.open(full).size == (10, 8)
    assert Image.open(full).getpixel((0, 0))[3] == 0


def test_illegal_and_duplicate_names_never_overwrite(tmp_path):
    first = unique_windows_name(tmp_path, "chair:1", ".png")
    first.touch()
    second = unique_windows_name(tmp_path, "chair:1", ".png")
    assert first.name == "chair_1.png"
    assert second.name == "chair_1_2.png"


def test_boolean_mask_exports_fully_opaque_foreground(tmp_path):
    image = Image.new("RGB", (4, 4), "red")
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    output = export_layer(image, mask, tmp_path / "bool.png", ExportMode.FULL_SIZE)
    assert Image.open(output).getchannel("A").getextrema() == (0, 255)


def test_reserved_windows_name_is_made_safe(tmp_path):
    assert unique_windows_name(tmp_path, "CON", ".png").name == "_CON.png"

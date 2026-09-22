from pathlib import Path

import numpy as np
from PIL import Image

from map_cutout.domain import FolderState, LayerState, MapState, ProjectState
from map_cutout.exporter import BatchExportRequest, BatchExporter


def fixture(tmp_path):
    source = tmp_path / "地图.jpg"
    Image.new("RGB", (20, 12), "blue").save(source)
    masks = tmp_path / "masks"; masks.mkdir()
    for name in ("chair", "door"):
        mask = np.zeros((12, 20), dtype=np.uint8); mask[2:8, 3:14] = 255
        Image.fromarray(mask).save(masks / f"{name}.png")
    state = MapState.new("map", str(source), 20, 12)
    state.folders = [FolderState("f", "家具")]
    state.layers += [
        LayerState("a", "chair1", "mask", "chair", str(masks / "chair.png"), True, False, "f"),
        LayerState("b", "door1", "mask", "door", str(masks / "door.png"), False),
    ]
    return BatchExporter(ProjectState("test", [state])), tmp_path / "out"


def names(report):
    return {path.name for path in report.exported}


def test_visible_scope_skips_hidden_but_all_scope_includes_it(tmp_path):
    exporter, output = fixture(tmp_path)
    visible = exporter.export(BatchExportRequest(output, scope="visible", mode="full_size"))
    all_layers = exporter.export(BatchExportRequest(output / "all", scope="all", mode="full_size"))
    assert names(visible) == {"chair1.png", "原始地图.png"}
    assert names(all_layers) == {"chair1.png", "door1.png", "原始地图.png"}


def test_folder_structure_is_optional(tmp_path):
    exporter, output = fixture(tmp_path)
    nested = exporter.export(BatchExportRequest(output, preserve_folders=True))
    flat = exporter.export(BatchExportRequest(output / "flat", preserve_folders=False))
    assert any(path.parent.name == "家具" for path in nested.exported)
    assert all(path.parent.name != "家具" for path in flat.exported)

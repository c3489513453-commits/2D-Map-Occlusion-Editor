from pathlib import Path
import json

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
    walkable = np.zeros((12, 20), dtype=np.uint8)
    walkable[3:11, 2:18] = 255
    Image.fromarray(walkable).save(masks / "walkable.png")
    state.walkable_layers = [LayerState("walk", "道路", "walkable", mask_path=str(masks / "walkable.png"))]
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


def test_occlusion_export_writes_full_size_images_and_actual_relative_names(tmp_path):
    exporter, output = fixture(tmp_path)
    state = exporter.project.maps[0]
    state.layers[1].name = "tree:1"
    state.layers[1].occlusion_lines = [[[1, 9], [10, 9]]]
    state.layers[2].name = "tree:1"
    state.layers[2].visible = True
    state.layers[2].occlusion_lines = [[[11, 9], [19, 9]]]

    report = exporter.export(BatchExportRequest(
        output,
        scope="all",
        mode="tight",
        include_occlusion=True,
    ))

    assert len(report.occlusion_manifests) == 1
    manifest_path = report.occlusion_manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 3
    assert manifest["map"] == {
        "width": 20,
        "height": 12,
        "coordinateOrigin": "top-left",
        "image": "map.png",
    }
    assert [item["image"] for item in manifest["occluders"]] == [
        "occluders/tree_1.png",
        "occluders/tree_1_2.png",
    ]
    assert all(item["imageMode"] == "full_size" for item in manifest["occluders"])
    for item in manifest["occluders"]:
        assert Image.open(manifest_path.parent / item["image"]).size == (20, 12)
    assert manifest["map"]["image"] == "map.png"
    assert Image.open(manifest_path.parent / "map.png").size == (20, 12)
    assert not (output / "tree_1.png").exists()
    assert not (output / "原始地图.png").exists()


def test_logic_package_does_not_duplicate_regular_layer_exports(tmp_path):
    exporter, output = fixture(tmp_path)
    state = exporter.project.maps[0]
    state.layers[1].occlusion_lines = [[[1, 9], [10, 9]]]

    report = exporter.export(BatchExportRequest(
        output, scope="all", mode="full_size", include_occlusion=True))

    relative = {path.relative_to(output).as_posix() for path in report.exported}
    assert "chair1.png" not in relative
    assert "door1.png" not in relative
    assert "原始地图.png" not in relative
    assert relative == {
        "地图/map.png", "地图/walkable.png", "地图/occlusion.json",
        "地图/occluders/chair1.png",
    }


def test_occlusion_export_uses_one_line_format(tmp_path):
    exporter, output = fixture(tmp_path)
    layer = exporter.project.maps[0].layers[1]
    layer.occlusion_lines = [[[3, 7], [13, 7]]]

    report = exporter.export(BatchExportRequest(output, scope="all", include_occlusion=True))

    manifest = json.loads(report.occlusion_manifests[0].read_text(encoding="utf-8"))
    assert manifest["version"] == 3
    assert manifest["occluders"][0]["lines"] == [[[3, 7], [13, 7]]]
    assert "regions" not in manifest["occluders"][0]


def test_occlusion_package_includes_full_size_walkable_mask(tmp_path):
    exporter, output = fixture(tmp_path)
    resource = exporter.project.maps[0].layers[1]
    resource.walkable_boundary_lines = [[[3, 6], [13, 6]]]
    exporter.project.maps[0].layers[2].walkable_boundary_lines = [[[3, 6], [13, 6]]]

    report = exporter.export(BatchExportRequest(output, scope="all", include_occlusion=True))

    manifest = json.loads(report.occlusion_manifests[0].read_text(encoding="utf-8"))
    assert manifest["walkableMask"] == "walkable.png"
    assert manifest["walkable"]["mask"] == "walkable.png"
    assert manifest["walkable"]["rule"] == "character_footprint_must_be_inside"
    assert manifest["walkable"]["composition"] == "manual_outside_resources_plus_resource_above_boundary_obstacle_wins"
    assert manifest["walkable"]["layers"][0]["name"] == "道路"
    assert manifest["resources"][0]["walkableBoundaryLines"] == [[[3, 6], [13, 6]]]
    exported = report.occlusion_manifests[0].parent / manifest["walkableMask"]
    assert Image.open(exported).size == (20, 12)
    assert np.asarray(Image.open(exported).convert("L"))[5, 5] == 255
    assert np.asarray(Image.open(exported).convert("L"))[7, 5] == 0


def test_resource_walkable_boundary_exports_even_without_occlusion_line(tmp_path):
    exporter, output = fixture(tmp_path)
    layer = exporter.project.maps[0].layers[1]
    layer.walkable_boundary_lines = [[[3, 6], [13, 6]]]

    report = exporter.export(BatchExportRequest(output, scope="all", include_occlusion=True))

    manifest = json.loads(report.occlusion_manifests[0].read_text(encoding="utf-8"))
    entry = next(item for item in manifest["resources"] if item["id"] == layer.id)
    assert entry["walkableBoundaryLines"] == [[[3, 6], [13, 6]]]
    assert entry["occlusionLines"] == []


def test_export_without_occlusion_option_keeps_existing_outputs(tmp_path):
    exporter, output = fixture(tmp_path)
    exporter.project.maps[0].layers[1].occlusion_lines = [[[1, 9], [10, 9]]]

    report = exporter.export(BatchExportRequest(output, scope="all", mode="tight"))

    assert report.occlusion_manifests == []
    assert not list(output.rglob("occlusion.json"))


def test_missing_source_image_is_reported_instead_of_crashing_export(tmp_path):
    exporter, output = fixture(tmp_path)
    source = Path(exporter.project.maps[0].source_path)
    source.unlink()

    report = exporter.export(BatchExportRequest(
        output, scope="all", include_occlusion=True))

    assert not report.exported
    assert report.failures[0]["layer_id"] == "source"
    assert "原图文件不存在" in report.failures[0]["reason"]

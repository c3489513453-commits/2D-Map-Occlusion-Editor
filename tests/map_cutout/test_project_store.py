from pathlib import Path
import json

import pytest
import numpy as np
from PIL import Image

from map_cutout.project_store import (
    ProjectSaveError,
    ProjectStore,
    SourceSizeMismatch,
)


def write_image(path: Path, size=(32, 24)) -> None:
    Image.new("RGB", size, "#7b5b42").save(path)


def test_import_folder_sorts_supported_images_and_ignores_other_files(tmp_path):
    write_image(tmp_path / "地下祭坛.png")
    write_image(tmp_path / "布莱庄园.jpg")
    (tmp_path / "说明.txt").write_text("x", encoding="utf-8")
    project = ProjectStore.create(tmp_path / "项目")

    imported = project.import_folder(tmp_path)

    assert [Path(item.source_path).name for item in imported] == [
        "地下祭坛.png",
        "布莱庄园.jpg",
    ]


def test_failed_save_keeps_previous_project_file(tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "项目")
    store.save()
    original = store.manifest_path.read_bytes()
    monkeypatch.setattr(
        Path,
        "replace",
        lambda *_: (_ for _ in ()).throw(PermissionError("read only")),
    )

    with pytest.raises(ProjectSaveError):
        store.save()

    assert store.manifest_path.read_bytes() == original


def test_save_and_load_preserves_unicode_source(tmp_path):
    image_path = tmp_path / "布莱庄园.png"
    write_image(image_path)
    store = ProjectStore.create(tmp_path / "项目")
    store.import_image(image_path)
    store.save()

    loaded = ProjectStore.load(store.root)

    assert Path(loaded.state.maps[0].source_path).name == "布莱庄园.png"


def test_relocate_rejects_different_image_size(tmp_path):
    original = tmp_path / "原图.png"
    replacement = tmp_path / "替换.png"
    write_image(original, (32, 24))
    write_image(replacement, (20, 20))
    store = ProjectStore.create(tmp_path / "项目")
    map_state = store.import_image(original)

    with pytest.raises(SourceSizeMismatch):
        store.relocate_source(map_state.id, replacement)


def test_old_project_layers_default_to_no_occlusion_regions(tmp_path):
    image_path = tmp_path / "地图.png"
    write_image(image_path)
    project_root = tmp_path / "项目"
    project_root.mkdir()
    (project_root / "project.json").write_text(json.dumps({
        "name": "旧项目",
        "maps": [{
            "id": "map-1",
            "source_path": str(image_path),
            "width": 32,
            "height": 24,
            "layers": [{
                "id": "layer-1",
                "name": "树",
                "kind": "mask",
                "class_name": "tree",
                "mask_path": "mask.png",
            }],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    loaded = ProjectStore.load(project_root)

    assert loaded.state.maps[0].layers[0].occlusion_regions == []


def test_save_and_load_preserves_occlusion_regions(tmp_path):
    image_path = tmp_path / "地图.png"
    write_image(image_path)
    store = ProjectStore.create(tmp_path / "项目")
    map_state = store.import_image(image_path)
    layer = map_state.layers[0]
    layer.occlusion_regions = [
        [[1.5, 2.0], [12.0, 2.0], [8.0, 18.5]],
        [[20.0, 4.0], [30.0, 4.0], [25.0, 16.0]],
    ]

    store.save()
    loaded = ProjectStore.load(store.root)

    assert loaded.state.maps[0].layers[0].occlusion_regions == layer.occlusion_regions


def test_import_image_starts_without_walkable_layers(tmp_path):
    image_path = tmp_path / "地图.png"
    write_image(image_path, (32, 24))
    store = ProjectStore.create(tmp_path / "项目")

    map_state = store.import_image(image_path)

    assert map_state.walkable_layers == []
    assert map_state.walkable_folders == []
    store.save()
    loaded = ProjectStore.load(store.root)
    assert loaded.state.maps[0].walkable_layers == []


def test_legacy_walkable_mask_migrates_to_layer(tmp_path):
    image_path = tmp_path / "地图.png"
    write_image(image_path, (32, 24))
    project_root = tmp_path / "项目"
    mask_path = project_root / "masks" / "map-1" / "walkable.png"
    mask_path.parent.mkdir(parents=True)
    Image.new("L", (32, 24), 255).save(mask_path)
    (project_root / "project.json").write_text(json.dumps({
        "name": "旧项目", "maps": [{"id": "map-1", "source_path": str(image_path),
        "width": 32, "height": 24, "walkable_mask_path": str(mask_path), "layers": []}]
    }, ensure_ascii=False), encoding="utf-8")

    loaded = ProjectStore.load(project_root)

    assert len(loaded.state.maps[0].walkable_layers) == 1
    assert loaded.state.maps[0].walkable_layers[0].name == "行走区域"
    assert loaded.state.maps[0].walkable_layers[0].mask_path == str(mask_path)

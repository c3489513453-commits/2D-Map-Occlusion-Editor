from pathlib import Path

import pytest
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

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from PIL import Image

from .domain import FolderState, LayerState, MapState, ProjectState


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ProjectSaveError(RuntimeError):
    pass


class SourceSizeMismatch(ValueError):
    def __init__(self, expected_width, expected_height, actual_width, actual_height):
        super().__init__(
            f"源图尺寸应为 {expected_width}×{expected_height}，"
            f"实际为 {actual_width}×{actual_height}"
        )


def _layer_from_dict(data: dict) -> LayerState:
    return LayerState(**data)


def _map_from_dict(data: dict) -> MapState:
    return MapState(
        id=data["id"],
        source_path=data["source_path"],
        width=data["width"],
        height=data["height"],
        layers=[_layer_from_dict(item) for item in data.get("layers", [])],
        folders=[FolderState(**item) for item in data.get("folders", [])],
        prompt=data.get("prompt", ""),
        threshold=data.get("threshold", 0.4),
    )


class ProjectStore:
    def __init__(self, root: Path, state: ProjectState):
        self.root = root
        self.state = state
        self.dirty = False

    @property
    def manifest_path(self) -> Path:
        return self.root / "project.json"

    @classmethod
    def create(cls, root: Path, name: str | None = None) -> "ProjectStore":
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        for child in ("masks", "thumbnails", "exports"):
            (root / child).mkdir(exist_ok=True)
        return cls(root, ProjectState(name=name or root.name))

    @classmethod
    def load(cls, root: Path) -> "ProjectStore":
        root = Path(root).resolve()
        data = json.loads((root / "project.json").read_text(encoding="utf-8"))
        state = ProjectState(
            name=data["name"],
            maps=[_map_from_dict(item) for item in data.get("maps", [])],
            current_map_id=data.get("current_map_id"),
            version=data.get("version", 1),
        )
        return cls(root, state)

    def import_folder(self, folder: Path) -> list[MapState]:
        paths = sorted(
            (
                path
                for path in Path(folder).iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            ),
            key=lambda path: path.name.casefold(),
        )
        return [self.import_image(path) for path in paths]

    def import_image(self, image_path: Path) -> MapState:
        image_path = Path(image_path).resolve()
        with Image.open(image_path) as image:
            width, height = image.size
            thumbnail = image.convert("RGB")
            thumbnail.thumbnail((360, 240))
        map_id = uuid.uuid5(uuid.NAMESPACE_URL, str(image_path)).hex[:16]
        existing = next((item for item in self.state.maps if item.id == map_id), None)
        if existing is not None:
            return existing
        state = MapState.new(map_id, str(image_path), width, height)
        self.state.maps.append(state)
        self.state.current_map_id = self.state.current_map_id or map_id
        thumbnail.save(self.root / "thumbnails" / f"{map_id}.jpg", quality=86)
        (self.root / "masks" / map_id).mkdir(parents=True, exist_ok=True)
        self.dirty = True
        return state

    def save(self) -> None:
        temporary = self.root / "project.json.tmp"
        recovery = self.root / "project.recovery.json"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(self.state.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.manifest_path)
        except Exception as exc:
            if temporary.exists():
                if recovery.exists():
                    recovery.unlink()
                temporary.rename(recovery)
            raise ProjectSaveError(f"项目保存失败：{exc}") from exc
        self.dirty = False

    def relocate_source(self, map_id: str, new_path: Path) -> MapState:
        new_path = Path(new_path).resolve()
        with Image.open(new_path) as image:
            actual_width, actual_height = image.size
        state = self.state.map_by_id(map_id)
        if (actual_width, actual_height) != (state.width, state.height):
            raise SourceSizeMismatch(
                state.width,
                state.height,
                actual_width,
                actual_height,
            )
        state.source_path = str(new_path)
        self.dirty = True
        return state

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class ExportMode(str, Enum):
    TIGHT = "tight"
    FULL_SIZE = "full_size"


@dataclass(frozen=True)
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class LayerState:
    id: str
    name: str
    kind: str
    class_name: str | None = None
    mask_path: str | None = None
    visible: bool = True
    locked: bool = False
    folder_id: str | None = None
    occlusion_regions: list[list[list[float]]] = field(default_factory=list)
    occlusion_lines: list[list[list[float]]] = field(default_factory=list)

    @classmethod
    def mask_layer(
        cls, layer_id: str, name: str, class_name: str, mask_path: str
    ) -> "LayerState":
        return cls(layer_id, name, "mask", class_name, mask_path)


@dataclass
class FolderState:
    id: str
    name: str
    visible: bool = True
    collapsed: bool = False


@dataclass
class MapState:
    id: str
    source_path: str
    width: int
    height: int
    walkable_mask_path: str | None = None
    layers: list[LayerState] = field(default_factory=list)
    folders: list[FolderState] = field(default_factory=list)
    walkable_layers: list[LayerState] = field(default_factory=list)
    walkable_folders: list[FolderState] = field(default_factory=list)
    prompt: str = ""
    threshold: float = 0.4

    @classmethod
    def new(
        cls, map_id: str, source_path: str, width: int, height: int
    ) -> "MapState":
        original = LayerState("original", "原始地图", "original", locked=True)
        return cls(map_id, source_path, width, height, layers=[original])

    def next_layer_name(self, class_name: str) -> str:
        prefix = class_name.strip().lower().replace(" ", "_") or "object"
        numbers = [
            int(layer.name[len(prefix) :])
            for layer in self.layers
            if layer.name.startswith(prefix)
            and layer.name[len(prefix) :].isdigit()
        ]
        return f"{prefix}{max(numbers, default=0) + 1}"

    def unique_layer_name(self, name: str) -> str:
        cleaned = " ".join(name.split()) or "新图层"
        existing = {layer.name for layer in self.layers}
        if cleaned not in existing:
            return cleaned
        number = 2
        while f"{cleaned}{number}" in existing:
            number += 1
        return f"{cleaned}{number}"

    def layer(self, layer_id: str) -> LayerState:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(layer_id)


@dataclass
class ProjectState:
    name: str
    maps: list[MapState] = field(default_factory=list)
    current_map_id: str | None = None
    version: int = 1
    character_path: str | None = None
    character_scale: float = 1.0

    def map_by_id(self, map_id: str) -> MapState:
        for map_state in self.maps:
            if map_state.id == map_id:
                return map_state
        raise KeyError(map_id)

    def to_dict(self) -> dict:
        return asdict(self)

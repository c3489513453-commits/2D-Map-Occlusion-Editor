from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .domain import FolderState, LayerState, MapState
from .masks import union_masks


class CreateLayerCommand:
    def __init__(self, map_state: MapState, layer: LayerState, index: int | None = None):
        self.map_state, self.layer, self.index = map_state, layer, index

    def execute(self):
        index = len(self.map_state.layers) if self.index is None else self.index
        if all(layer.id != self.layer.id for layer in self.map_state.layers):
            self.map_state.layers.insert(index, self.layer)
        return self.layer

    def undo(self):
        self.map_state.layers.remove(self.layer)


class DeleteLayerCommand:
    def __init__(self, map_state: MapState, layer_id: str):
        self.map_state, self.layer_id = map_state, layer_id
        self.layer = None
        self.index = None

    def execute(self):
        self.layer = self.map_state.layer(self.layer_id)
        if self.layer.kind == "original":
            raise ValueError("原始地图图层不能删除")
        self.index = self.map_state.layers.index(self.layer)
        self.map_state.layers.pop(self.index)
        return self.layer

    def undo(self):
        self.map_state.layers.insert(self.index, self.layer)


class _SetLayerAttributeCommand:
    attribute = ""

    def __init__(self, map_state: MapState, layer_id: str, value):
        self.layer = map_state.layer(layer_id)
        self.value = value
        self.old_value = getattr(self.layer, self.attribute)

    def execute(self):
        setattr(self.layer, self.attribute, self.value)
        return self.layer

    def undo(self):
        setattr(self.layer, self.attribute, self.old_value)


class RenameLayerCommand(_SetLayerAttributeCommand):
    attribute = "name"


class SetLayerVisibilityCommand(_SetLayerAttributeCommand):
    attribute = "visible"


class SetLayerLockCommand(_SetLayerAttributeCommand):
    attribute = "locked"


class AssignLayerFolderCommand(_SetLayerAttributeCommand):
    attribute = "folder_id"


class MoveLayerCommand:
    def __init__(self, map_state: MapState, layer_id: str, index: int):
        self.map_state, self.layer_id, self.index = map_state, layer_id, index
        self.old_index = None

    def execute(self):
        layer = self.map_state.layer(self.layer_id)
        if layer.kind == "original":
            raise ValueError("原始地图必须保留在底层")
        current = self.map_state.layers.index(layer)
        if self.old_index is None:
            self.old_index = current
        self.map_state.layers.pop(current)
        self.map_state.layers.insert(max(1, self.index), layer)
        return layer

    def undo(self):
        layer = self.map_state.layer(self.layer_id)
        self.map_state.layers.remove(layer)
        self.map_state.layers.insert(self.old_index, layer)


class CreateFolderCommand:
    def __init__(self, map_state: MapState, name: str, folder_id: str | None = None):
        self.map_state = map_state
        self.folder = FolderState(folder_id or uuid4().hex, name)

    def execute(self):
        if all(folder.id != self.folder.id for folder in self.map_state.folders):
            self.map_state.folders.append(self.folder)
        return self.folder

    def undo(self):
        self.map_state.folders.remove(self.folder)


class DeleteFolderCommand:
    def __init__(self, map_state: MapState, folder_id: str):
        self.map_state, self.folder_id = map_state, folder_id
        self.folder = None
        self.index = None
        self.members = []

    def execute(self):
        self.folder = next(folder for folder in self.map_state.folders if folder.id == self.folder_id)
        self.index = self.map_state.folders.index(self.folder)
        self.members = [layer for layer in self.map_state.layers if layer.folder_id == self.folder_id]
        self.map_state.folders.pop(self.index)
        for layer in self.members:
            layer.folder_id = None
        return self.folder

    def undo(self):
        self.map_state.folders.insert(self.index, self.folder)
        for layer in self.members:
            layer.folder_id = self.folder_id


class MergeLayersCommand:
    def __init__(self, map_state: MapState, layer_ids: list[str], mask_repository):
        if len(layer_ids) < 2:
            raise ValueError("至少选择两个图层才能合并")
        self.map_state, self.layer_ids, self.mask_repository = map_state, layer_ids, mask_repository
        self.previous_visibility = {}
        self.merged = None

    def execute(self):
        sources = [self.map_state.layer(layer_id) for layer_id in self.layer_ids]
        if self.merged is None:
            mask = union_masks([self.mask_repository.load(layer.mask_path) for layer in sources])
            layer_id = uuid4().hex
            class_name = sources[0].class_name or "merged"
            path = self.mask_repository.save(layer_id, mask)
            self.merged = LayerState.mask_layer(
                layer_id, self.map_state.next_layer_name(class_name), class_name, path)
        self.previous_visibility = {layer.id: layer.visible for layer in sources}
        for layer in sources:
            layer.visible = False
        if self.merged not in self.map_state.layers:
            self.map_state.layers.append(self.merged)
        return self.merged

    def undo(self):
        self.map_state.layers.remove(self.merged)
        for layer_id, visible in self.previous_visibility.items():
            self.map_state.layer(layer_id).visible = visible


import numpy as np

from map_cutout.commands import (
    CreateFolderCommand,
    DeleteLayerCommand,
    MergeLayersCommand,
    MoveLayerCommand,
    RenameLayerCommand,
    SetLayerVisibilityCommand,
)
from map_cutout.domain import LayerState, MapState


class FakeMaskRepository:
    def __init__(self, masks):
        self.masks = dict(masks)

    def load(self, path):
        return self.masks[path]

    def save(self, layer_id, mask):
        path = f"{layer_id}.png"
        self.masks[path] = mask.copy()
        return path

    def delete(self, path):
        self.masks.pop(path, None)


def sample_map():
    state = MapState.new("map", "map.png", 8, 6)
    state.layers += [
        LayerState.mask_layer("a", "chair1", "chair", "a.png"),
        LayerState.mask_layer("b", "chair2", "chair", "b.png"),
    ]
    return state


def test_merge_keeps_sources_and_hides_them_and_undo_restores():
    state = sample_map()
    repo = FakeMaskRepository({
        "a.png": np.eye(6, 8, dtype=bool),
        "b.png": np.fliplr(np.eye(6, 8, dtype=bool)),
    })
    command = MergeLayersCommand(state, ["a", "b"], repo)

    merged = command.execute()

    assert merged.visible is True
    assert state.layer("a").visible is False
    assert state.layer("b").visible is False
    assert np.array_equal(repo.load(merged.mask_path), repo.load("a.png") | repo.load("b.png"))
    command.undo()
    assert state.layer("a").visible is True
    assert state.layer("b").visible is True
    assert all(layer.id != merged.id for layer in state.layers)


def test_layer_property_delete_move_and_folder_commands_are_reversible():
    state = sample_map()
    rename = RenameLayerCommand(state, "a", "seat")
    visible = SetLayerVisibilityCommand(state, "a", False)
    move = MoveLayerCommand(state, "b", 1)
    folder = CreateFolderCommand(state, "chairs")
    delete = DeleteLayerCommand(state, "a")

    rename.execute(); visible.execute(); move.execute(); created = folder.execute(); delete.execute()
    assert state.layer("b") is state.layers[1]
    assert created.name == "chairs"
    assert all(layer.id != "a" for layer in state.layers)

    delete.undo(); folder.undo(); move.undo(); visible.undo(); rename.undo()
    assert state.layer("a").name == "chair1"
    assert state.layer("a").visible is True
    assert [layer.id for layer in state.layers] == ["original", "a", "b"]
    assert state.folders == []

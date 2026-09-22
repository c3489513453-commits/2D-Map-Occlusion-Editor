from map_cutout.domain import LayerState, MapState


def test_map_assigns_next_class_name_without_overwriting():
    state = MapState.new("map-1", "D:/素材/庄园.png", 2048, 2048)
    state.layers.extend(
        [
            LayerState.mask_layer("a", "chair1", "chair", "masks/a.png"),
            LayerState.mask_layer("b", "chair3", "chair", "masks/b.png"),
        ]
    )

    assert state.next_layer_name("chair") == "chair4"


def test_named_layer_keeps_the_entered_name_until_it_collides():
    state = MapState.new("map-1", "D:/素材/庄园.png", 100, 100)

    assert state.unique_layer_name("  城门  ") == "城门"
    state.layers.append(LayerState.mask_layer("a", "城门", "城门", "a.png"))
    assert state.unique_layer_name("城门") == "城门2"


def test_original_layer_is_bottom_visible_and_locked():
    state = MapState.new("map-1", "D:/素材/庄园.png", 2048, 2048)

    original = state.layers[-1]
    assert original.kind == "original"
    assert original.visible is True
    assert original.locked is True

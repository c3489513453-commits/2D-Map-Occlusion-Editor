import time
import base64
import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from map_cutout.config import AppConfig
from map_cutout.domain import LayerState
from map_cutout.jobs import JobManager
from map_cutout.project_store import ProjectStore
from map_cutout.web_app import AppServices, DiskMaskRepository, create_app
import map_cutout.web_app as web_app


class FakeInference:
    def __init__(self):
        self.error = None

    def detect(self, image, prompt, threshold):
        if self.error:
            raise self.error
        return []


def services(tmp_path):
    project = ProjectStore.create(tmp_path / "project", "test")
    image_path = tmp_path / "地图.png"
    Image.new("RGB", (24, 16), "white").save(image_path)
    project.import_image(image_path)
    return AppServices(project, FakeInference(), JobManager(max_workers=1))


def wait_for_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_app_rejects_non_loopback_host(tmp_path):
    with pytest.raises(ValueError, match="仅允许本机"):
        create_app(AppConfig(project_root=tmp_path, host="0.0.0.0"), services(tmp_path))


def test_maps_and_layers_are_available(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_id = app_services.project.state.maps[0].id

    assert client.get("/api/maps").json()[0]["id"] == map_id
    layers = client.get(f"/api/maps/{map_id}/layers").json()
    assert layers[0]["kind"] == "original"
    assert client.get(f"/api/maps/{map_id}/image").status_code == 200


def test_page_has_resource_and_walkable_layer_switch(tmp_path):
    client = TestClient(create_app(AppConfig(project_root=tmp_path), services(tmp_path)))

    html = client.get("/").text

    assert 'id="layer-mode"' in html
    assert 'data-mode="resources"' in html
    assert 'data-mode="walkable"' in html


def test_character_png_and_scale_persist_in_project(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 12), (255, 0, 0, 255)).save(buffer, format="PNG")

    saved = client.put("/api/character", json={
        "png_base64": base64.b64encode(buffer.getvalue()).decode("ascii"), "scale": 1.5,
    })

    assert saved.status_code == 200
    assert client.get("/api/character").status_code == 200
    assert app_services.project.state.character_scale == 1.5
    app_services.project.save()
    loaded = ProjectStore.load(app_services.project.root)
    assert Path(loaded.state.character_path).is_file()
    assert loaded.state.character_scale == 1.5


def test_character_can_be_deleted_from_project(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 12), (255, 0, 0, 255)).save(buffer, format="PNG")
    client.put("/api/character", json={
        "png_base64": base64.b64encode(buffer.getvalue()).decode("ascii"), "scale": 1,
    })
    path = Path(app_services.project.state.character_path)

    response = client.delete("/api/character")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert app_services.project.state.character_path is None
    assert not path.exists()
    assert client.get("/api/character/info").json()["available"] is False


def test_cuda_oom_becomes_chinese_failed_job_without_layers(tmp_path):
    app_services = services(tmp_path)
    app_services.inference.error = RuntimeError("CUDA out of memory")
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_id = app_services.project.state.maps[0].id
    before = client.get(f"/api/maps/{map_id}/layers").json()

    response = client.post(f"/api/maps/{map_id}/detect", json={"prompt": "wall.", "threshold": .4})
    job = wait_for_job(client, response.json()["job_id"])
    after = client.get(f"/api/maps/{map_id}/layers").json()

    assert job["state"] == "failed"
    assert "显存不足" in job["message"]
    assert after == before


def test_polygon_edit_changes_existing_mask_without_adding_a_layer(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    repository = DiskMaskRepository(app_services.project, map_state.id)
    mask = np.zeros((map_state.height, map_state.width), dtype=np.uint8)
    mask[2:6, 2:6] = 1
    path = repository.save("chair", mask)
    map_state.layers.append(LayerState.mask_layer("chair", "chair1", "chair", path))
    before = client.get(f"/api/maps/{map_state.id}/layers").json()

    added = client.post(
        f"/api/maps/{map_state.id}/layers/chair/paint",
        json={"shape": "polygon", "points": [[10, 2], [20, 2], [20, 10], [10, 10]], "value": 255},
    )
    assert added.status_code == 200
    image = np.asarray(Image.open(path).convert("L"))
    assert image[3, 3] == 255
    assert image[6, 14] == 255
    assert image[0, 0] == 0
    assert client.get(f"/api/maps/{map_state.id}/layers/chair/mask").headers["cache-control"] == "no-store"

    added_again = client.post(
        f"/api/maps/{map_state.id}/layers/chair/paint",
        json={"shape": "polygon", "points": [[2, 11], [8, 11], [8, 15], [2, 15]], "value": 255},
    )
    assert added_again.status_code == 200
    brushed = client.post(
        f"/api/maps/{map_state.id}/layers/chair/paint",
        json={"points": [[16, 13], [18, 13]], "radius": 2, "value": 255},
    )
    assert brushed.status_code == 200
    image = np.asarray(Image.open(path).convert("L"))
    assert image[3, 3] == 255
    assert image[6, 14] == 255
    assert image[13, 4] == 255
    assert image[13, 17] == 255

    removed = client.post(
        f"/api/maps/{map_state.id}/layers/chair/paint",
        json={"shape": "polygon", "points": [[2, 2], [6, 2], [6, 6], [2, 6]], "value": 0},
    )
    assert removed.status_code == 200
    image = np.asarray(Image.open(path).convert("L"))
    assert image[3, 3] == 0
    assert image[6, 14] == 255
    assert image[13, 4] == 255
    assert image[13, 17] == 255
    after = client.get(f"/api/maps/{map_state.id}/layers").json()
    assert [layer["id"] for layer in after] == [layer["id"] for layer in before]


def test_blank_layer_can_be_painted_without_a_prior_region(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    before = client.get(f"/api/maps/{map_state.id}/layers").json()

    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()
    assert created["name"] == "新图层"
    assert created["kind"] == "mask"
    assert int(np.asarray(Image.open(created["mask_path"]).convert("L")).max()) == 0

    first = client.post(
        f"/api/maps/{map_state.id}/layers/{created['id']}/paint",
        json={"points": [[4, 4], [6, 4]], "radius": 2, "value": 255},
    )
    second = client.post(
        f"/api/maps/{map_state.id}/layers/{created['id']}/paint",
        json={"points": [[14, 8]], "radius": 2, "value": 255},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    mask = np.asarray(Image.open(created["mask_path"]).convert("L"))
    assert mask[4, 5] == 255
    assert mask[8, 14] == 255
    assert mask[0, 0] == 0
    after = client.get(f"/api/maps/{map_state.id}/layers").json()
    assert len(after) == len(before) + 1


def test_walkable_mask_is_independent_and_can_be_painted(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]

    created = client.post(f"/api/maps/{map_state.id}/walkable/layers", json={"name": "道路"}).json()
    response = client.post(
        f"/api/maps/{map_state.id}/walkable/layers/{created['id']}/paint",
        json={"shape": "polygon", "points": [[2, 2], [12, 2], [12, 10], [2, 10]], "value": 255},
    )

    assert response.status_code == 200
    mask = np.asarray(Image.open(created["mask_path"]).convert("L"))
    assert mask[5, 5] == 255
    assert mask[0, 0] == 0
    assert client.get(f"/api/maps/{map_state.id}/walkable/layers/{created['id']}/mask").status_code == 200
    assert [layer.kind for layer in map_state.layers] == ["original"]

    folder = client.post(f"/api/maps/{map_state.id}/walkable/folders", json={"name": "一楼"}).json()
    patched = client.patch(
        f"/api/maps/{map_state.id}/walkable/layers/{created['id']}",
        json={"name": "主路", "visible": False, "folder_id": folder["id"]},
    ).json()
    assert patched["name"] == "主路"
    assert patched["visible"] is False
    assert patched["folder_id"] == folder["id"]


def test_box_recognition_can_be_added_to_a_walkable_layer(tmp_path):
    app_services = services(tmp_path)
    map_state = app_services.project.state.maps[0]

    class FullBox:
        def segment_box(self, image, box):
            return np.ones((image.height, image.width), dtype=bool)

    app_services.inference = FullBox()
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    layer = client.post(
        f"/api/maps/{map_state.id}/walkable/layers", json={"name": "道路"}
    ).json()

    job = wait_for_job(client, client.post(
        f"/api/maps/{map_state.id}/walkable/layers/{layer['id']}/segment-add",
        json={"box": [0, 0, map_state.width, map_state.height]},
    ).json()["job_id"])

    assert job["state"] == "completed"
    assert job["result"]["added"] is True
    assert int(np.asarray(Image.open(layer["mask_path"]).convert("L")).min()) == 255
    assert [item.kind for item in map_state.layers] == ["original"]


def test_point_preview_commit_excludes_resource_masks_from_manual_walkable(tmp_path):
    app_services = services(tmp_path)
    map_state = app_services.project.state.maps[0]

    class FullPoints:
        def segment_points(self, image, points, labels, box):
            return np.ones((image.height, image.width), dtype=bool)

    app_services.inference = FullPoints()
    repository = DiskMaskRepository(app_services.project, map_state.id)
    occupied = repository.save("resource", np.ones((map_state.height, map_state.width), dtype=bool))
    map_state.layers.append(LayerState.mask_layer("resource", "资源", "object", occupied))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    layer = client.post(
        f"/api/maps/{map_state.id}/walkable/layers", json={"name": "道路"}
    ).json()

    preview_job = wait_for_job(client, client.post(
        f"/api/maps/{map_state.id}/segment",
        json={"points": [[4, 4]], "labels": [1], "target_kind": "walkable"},
    ).json()["job_id"])
    assert preview_job["result"]["preview_id"]
    committed = client.post(
        f"/api/maps/{map_state.id}/walkable/layers/{layer['id']}/segment-commit",
        json={"preview_id": preview_job["result"]["preview_id"]},
    )

    assert committed.status_code == 200
    assert int(np.asarray(Image.open(layer["mask_path"]).convert("L")).max()) == 0


def test_walkable_boundary_lines_can_be_saved_and_are_normalized(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()

    response = client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/walkable-boundary-lines",
        json={"lines": [[[2, 3], [10.5, 4]]]},
    )

    assert response.status_code == 200
    assert response.json()["walkable_boundary_lines"] == [[[2.0, 3.0], [10.5, 4.0]]]
    assert map_state.layer(created["id"]).walkable_boundary_lines == [
        [[2.0, 3.0], [10.5, 4.0]]
    ]


def test_auto_walkable_boundaries_only_fill_layers_without_a_line(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    repository = DiskMaskRepository(app_services.project, map_state.id)
    mask = np.zeros((map_state.height, map_state.width), dtype=bool)
    mask[2:12, 3:13] = True
    first = LayerState.mask_layer("first", "木桶", "barrel", repository.save("first", mask))
    second = LayerState.mask_layer("second", "箱子", "box", repository.save("second", mask))
    second.walkable_boundary_lines = [[[3.0, 8.0], [12.0, 8.0]]]
    map_state.layers.extend([first, second])

    generated = client.post(f"/api/maps/{map_state.id}/walkable-boundary-lines/auto")
    generated_again = client.post(f"/api/maps/{map_state.id}/walkable-boundary-lines/auto")

    assert generated.status_code == 200
    assert generated.json() == {"created": 1, "skipped": 1}
    assert first.walkable_boundary_lines == [[[3.0, 9.0], [12.0, 9.0]]]
    assert second.walkable_boundary_lines == [[[3.0, 8.0], [12.0, 8.0]]]
    assert generated_again.json() == {"created": 0, "skipped": 2}


def test_painting_walkable_automatically_excludes_resource_masks(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    repository = DiskMaskRepository(app_services.project, map_state.id)
    resource = np.zeros((map_state.height, map_state.width), dtype=bool)
    resource[4:10, 7:14] = True
    map_state.layers.append(LayerState.mask_layer(
        "resource", "木桶", "barrel", repository.save("resource", resource)
    ))
    layer = client.post(
        f"/api/maps/{map_state.id}/walkable/layers", json={"name": "道路"}
    ).json()

    response = client.post(
        f"/api/maps/{map_state.id}/walkable/layers/{layer['id']}/paint",
        json={"shape": "polygon", "points": [[1, 1], [20, 1], [20, 14], [1, 14]], "value": 255},
    )

    assert response.status_code == 200
    saved = np.asarray(Image.open(layer["mask_path"]).convert("L")) > 0
    assert saved[2, 2]
    assert not saved[5, 8]


def test_final_walkable_mask_merges_manual_and_resource_passable_area(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    repository = DiskMaskRepository(app_services.project, map_state.id)
    resource = np.zeros((map_state.height, map_state.width), dtype=bool)
    resource[2:12, 3:13] = True
    item = LayerState.mask_layer("resource", "木桶", "barrel", repository.save("resource", resource))
    item.walkable_boundary_lines = [[[3.0, 9.0], [12.0, 9.0]]]
    map_state.layers.append(item)
    manual = np.zeros((map_state.height, map_state.width), dtype=bool)
    manual[1:15, 1:22] = True
    map_state.walkable_layers.append(LayerState(
        "road", "道路", "walkable", mask_path=repository.save("walkable-road", manual)
    ))

    response = client.get(f"/api/maps/{map_state.id}/walkable/final-mask")

    assert response.status_code == 200
    result = np.asarray(Image.open(io.BytesIO(response.content)).convert("L")) > 0
    assert result[1, 1]
    assert result[5, 5]
    assert not result[10, 5]


def test_legacy_locked_mask_can_still_be_edited_after_lock_control_is_removed(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()
    map_state.layer(created["id"]).locked = True

    response = client.post(
        f"/api/maps/{map_state.id}/layers/{created['id']}/paint",
        json={"points": [[3, 3]], "radius": 2, "value": 255},
    )

    assert response.status_code == 200


def test_occlusion_regions_can_be_saved_and_undone(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()
    regions = [[[1, 1], [20, 1], [20, 12], [1, 12]]]

    updated = client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/occlusion-regions",
        json={"regions": regions},
    )

    assert updated.status_code == 200
    assert updated.json()["occlusion_regions"] == regions
    assert app_services.project.dirty is True
    undone = client.post(f"/api/maps/{map_state.id}/undo")
    assert undone.status_code == 200
    layer = client.get(f"/api/maps/{map_state.id}/layers").json()[0]
    assert layer["id"] == created["id"]
    assert layer["occlusion_regions"] == []


def test_occlusion_lines_can_be_saved_and_undone(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()
    lines = [[[1, 5], [10, 6], [20, 5]]]

    updated = client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/occlusion-lines",
        json={"lines": lines},
    )

    assert updated.status_code == 200
    assert updated.json()["occlusion_lines"] == lines
    undone = client.post(f"/api/maps/{map_state.id}/undo")
    assert undone.status_code == 200
    layer = next(item for item in client.get(f"/api/maps/{map_state.id}/layers").json()
                 if item["id"] == created["id"])
    assert layer["occlusion_lines"] == []


def test_auto_baselines_fill_only_layers_without_existing_lines(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    repository = DiskMaskRepository(app_services.project, map_state.id)
    first = np.zeros((map_state.height, map_state.width), dtype=np.uint8)
    first[2:7, 2:9] = 255
    second = np.zeros_like(first)
    second[4:10, 12:20] = 255
    map_state.layers += [
        LayerState.mask_layer("first", "first", "object", repository.save("first", first)),
        LayerState.mask_layer("second", "second", "object", repository.save("second", second)),
    ]
    map_state.layer("second").occlusion_lines = [[[12, 9], [19, 9]]]

    response = client.post(f"/api/maps/{map_state.id}/occlusion-lines/auto")

    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert map_state.layer("first").occlusion_lines
    assert map_state.layer("second").occlusion_lines == [[[12, 9], [19, 9]]]


@pytest.mark.parametrize("regions", [
    [[[1, 1], [2, 2]]],
    [[[1, 1], [1, 1], [1, 1]]],
    [[[1, 1], [2, 2], [3, 3]]],
    [[[-1, 1], [2, 2], [3, 3]]],
    [[[1, 1], [25, 2], [3, 3]]],
    "not-a-list",
])
def test_occlusion_regions_reject_invalid_geometry(tmp_path, regions):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()

    response = client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/occlusion-regions",
        json={"regions": regions},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "遮挡区域格式不正确"


@pytest.mark.parametrize("number", ["NaN", "Infinity"])
def test_occlusion_regions_reject_non_finite_numbers(tmp_path, number):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()

    response = client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/occlusion-regions",
        content=f'{{"regions":[[[1,1],[2,2],[{number},3]]]}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "遮挡区域格式不正确"


def test_original_layer_cannot_have_occlusion_regions(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]

    response = client.put(
        f"/api/maps/{map_state.id}/layers/original/occlusion-regions",
        json={"regions": [[[1, 1], [10, 1], [10, 10]]]},
    )

    assert response.status_code == 400
    assert "蒙版" in response.json()["detail"]


def test_export_api_can_include_occlusion_manifest(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={}).json()
    client.put(
        f"/api/maps/{map_state.id}/layers/{created['id']}/occlusion-lines",
        json={"lines": [[[1, 12], [20, 12]]]},
    )
    output = tmp_path / "遮挡导出"

    response = client.post("/api/export", json={
        "output_dir": str(output),
        "scope": "all",
        "map_ids": [map_state.id],
        "include_occlusion": True,
    })

    assert response.status_code == 200
    manifests = response.json()["occlusion_manifests"]
    assert len(manifests) == 1
    assert Path(manifests[0]).is_file()


def test_deleting_a_map_keeps_the_source_file(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    first = app_services.project.state.maps[0]
    second_path = tmp_path / "第二张.png"
    Image.new("RGB", (8, 8), "blue").save(second_path)
    second = client.post("/api/import/image", json={"path": str(second_path)}).json()

    deleted = client.delete(f"/api/maps/{first.id}")
    assert deleted.status_code == 200
    assert Path(first.source_path).is_file()
    remaining = client.get("/api/maps").json()
    assert [item["id"] for item in remaining] == [second["id"]]
    assert client.get(f"/api/maps/{first.id}/layers").status_code == 404

    renamed = client.patch(
        f"/api/maps/{second['id']}/layers/original",
        json={"name": "底图"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "底图"


def test_folder_can_hold_a_layer_and_then_be_deleted(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    created = client.post(f"/api/maps/{map_state.id}/layers", json={"name": "城门"}).json()
    folder = client.post(f"/api/maps/{map_state.id}/folders", json={"name": "建筑"}).json()

    moved = client.patch(
        f"/api/maps/{map_state.id}/layers/{created['id']}",
        json={"folder_id": folder["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder["id"]

    deleted = client.delete(f"/api/maps/{map_state.id}/folders/{folder['id']}")
    assert deleted.status_code == 200
    layers = client.get(f"/api/maps/{map_state.id}/layers").json()
    layer = next(item for item in layers if item["id"] == created["id"])
    assert layer["folder_id"] is None
    maps = client.get("/api/maps").json()
    assert maps[0]["folders"] == []


def test_new_named_layer_starts_empty_and_lasso_adds_only_its_interior(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_state = app_services.project.state.maps[0]
    before = client.get(f"/api/maps/{map_state.id}/layers").json()

    created = client.post(f"/api/maps/{map_state.id}/layers", json={"name": "城门"}).json()
    assert created["name"] == "城门"
    assert created["kind"] == "mask"
    mask = np.asarray(Image.open(created["mask_path"]).convert("L"))
    assert mask.shape == (map_state.height, map_state.width)
    assert int(mask.max()) == 0

    painted = client.post(
        f"/api/maps/{map_state.id}/layers/{created['id']}/paint",
        json={"shape": "polygon", "points": [[2, 2], [10, 2], [10, 8], [2, 8]], "value": 255},
    )
    assert painted.status_code == 200
    mask = np.asarray(Image.open(created["mask_path"]).convert("L"))
    assert mask[4, 5] == 255
    assert mask[0, 0] == 0

    duplicate = client.post(f"/api/maps/{map_state.id}/layers", json={"name": "城门"}).json()
    assert duplicate["name"] == "城门2"
    after = client.get(f"/api/maps/{map_state.id}/layers").json()
    assert len(after) == len(before) + 2
    assert after[0]["id"] == duplicate["id"]


def test_box_segment_keeps_existing_masks_and_only_the_new_part(tmp_path):
    app_services = services(tmp_path)
    map_state = app_services.project.state.maps[0]

    class FullBox:
        def segment_box(self, image, box):
            return np.ones((image.height, image.width), dtype=bool)

    app_services.inference = FullBox()
    repository = DiskMaskRepository(app_services.project, map_state.id)
    existing = np.zeros((map_state.height, map_state.width), dtype=bool)
    existing[:, :8] = True
    path = repository.save("old", existing)
    map_state.layers.append(LayerState.mask_layer("old", "旧蒙版", "object", path))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))

    job = wait_for_job(client, client.post(
        f"/api/maps/{map_state.id}/segment",
        json={"box": [0, 0, map_state.width, map_state.height], "name": "新区"},
    ).json()["job_id"])
    assert job["state"] == "completed"
    preview = np.asarray(Image.open(
        app_services.project.root / "masks" / f"preview-{job['result']['preview_id']}.png"
    ).convert("L"))
    assert int(preview[:, :8].max()) == 0
    assert int(preview[:, 8:].min()) == 255

    layer = client.post(
        f"/api/maps/{map_state.id}/segment/commit",
        json={"preview_id": job["result"]["preview_id"], "name": "新区"},
    ).json()
    saved = np.asarray(Image.open(layer["mask_path"]).convert("L"))
    assert int(saved[:, :8].max()) == 0
    assert int(saved[:, 8:].min()) == 255


def test_box_on_an_edited_layer_unions_the_whole_recognition_even_over_other_masks(tmp_path):
    app_services = services(tmp_path)
    map_state = app_services.project.state.maps[0]

    class FullBox:
        def segment_box(self, image, box):
            return np.ones((image.height, image.width), dtype=bool)

    app_services.inference = FullBox()
    repository = DiskMaskRepository(app_services.project, map_state.id)
    existing = np.zeros((map_state.height, map_state.width), dtype=bool)
    existing[:, :8] = True
    old_path = repository.save("old", existing)
    map_state.layers.append(LayerState.mask_layer("old", "旧蒙版", "object", old_path))
    editing = np.zeros((map_state.height, map_state.width), dtype=bool)
    editing[:2, 20:22] = True
    edit_path = repository.save("edit", editing)
    map_state.layers.append(LayerState.mask_layer("edit", "正在改", "object", edit_path))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    before = client.get(f"/api/maps/{map_state.id}/layers").json()

    job = wait_for_job(client, client.post(
        f"/api/maps/{map_state.id}/layers/edit/segment-add",
        json={"box": [0, 0, map_state.width, map_state.height]},
    ).json()["job_id"])

    assert job["state"] == "completed"
    assert job["result"]["added"] is True
    saved = np.asarray(Image.open(edit_path).convert("L"))
    assert saved[0, 21] == 255
    assert int(saved.min()) == 255
    untouched = np.asarray(Image.open(old_path).convert("L"))
    assert int(untouched[:, :8].min()) == 255
    assert client.get(f"/api/maps/{map_state.id}/layers").json() == before


def test_box_segment_adds_nothing_when_the_place_is_already_covered(tmp_path):
    app_services = services(tmp_path)
    map_state = app_services.project.state.maps[0]

    class FullBox:
        def segment_box(self, image, box):
            return np.ones((image.height, image.width), dtype=bool)

    app_services.inference = FullBox()
    repository = DiskMaskRepository(app_services.project, map_state.id)
    path = repository.save("old", np.ones((map_state.height, map_state.width), dtype=bool))
    map_state.layers.append(LayerState.mask_layer("old", "旧蒙版", "object", path))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    before = client.get(f"/api/maps/{map_state.id}/layers").json()

    job = wait_for_job(client, client.post(
        f"/api/maps/{map_state.id}/segment",
        json={"box": [0, 0, map_state.width, map_state.height], "name": "新区"},
    ).json()["job_id"])

    assert job["state"] == "completed"
    assert job["result"]["preview_id"] is None
    assert client.get(f"/api/maps/{map_state.id}/layers").json() == before


def test_project_save_and_layer_patch(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_id = app_services.project.state.maps[0].id
    response = client.patch(
        f"/api/maps/{map_id}/layers/original", json={"visible": False})
    assert response.json()["visible"] is False
    assert client.post("/api/projects/save").json()["saved"] is True
    assert app_services.project.manifest_path.exists()


def test_saved_project_is_restored_when_the_app_starts_again(tmp_path, monkeypatch):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    expected_map_id = app_services.project.state.maps[0].id
    assert client.post("/api/projects/save").status_code == 200
    monkeypatch.setattr(web_app.InferenceService, "default", lambda config: FakeInference())

    restarted = TestClient(create_app(AppConfig(project_root=tmp_path)))

    assert [item["id"] for item in restarted.get("/api/maps").json()] == [expected_map_id]


def test_opened_project_becomes_the_next_startup_project(tmp_path, monkeypatch):
    first_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), first_services))
    opened = ProjectStore.create(tmp_path / "另一个项目", "另一个项目")
    image_path = tmp_path / "另一个地图.png"
    Image.new("RGB", (12, 10), "blue").save(image_path)
    expected_map_id = opened.import_image(image_path).id
    opened.save()

    response = client.post("/api/projects/open", json={"path": str(opened.root)})
    monkeypatch.setattr(web_app.InferenceService, "default", lambda config: FakeInference())
    restarted = TestClient(create_app(AppConfig(project_root=tmp_path)))

    assert response.status_code == 200
    assert [item["id"] for item in restarted.get("/api/maps").json()] == [expected_map_id]


def test_invalid_last_project_record_falls_back_to_a_blank_project(tmp_path, monkeypatch):
    (tmp_path / ".map-cutout-last-project.json").write_text(
        '{"project_path": "Z:/已经不存在/项目"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app.InferenceService, "default", lambda config: FakeInference())

    restarted = TestClient(create_app(AppConfig(project_root=tmp_path)))

    assert restarted.get("/api/maps").json() == []

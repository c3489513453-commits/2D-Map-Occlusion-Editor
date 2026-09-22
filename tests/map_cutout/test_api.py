import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from map_cutout.config import AppConfig
from map_cutout.domain import LayerState
from map_cutout.jobs import JobManager
from map_cutout.project_store import ProjectStore
from map_cutout.web_app import AppServices, DiskMaskRepository, create_app


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


def test_project_save_and_layer_patch(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_id = app_services.project.state.maps[0].id
    response = client.patch(
        f"/api/maps/{map_id}/layers/original", json={"visible": False})
    assert response.json()["visible"] is False
    assert client.post("/api/projects/save").json()["saved"] is True
    assert app_services.project.manifest_path.exists()

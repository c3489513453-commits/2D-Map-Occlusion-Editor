import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from map_cutout.config import AppConfig
from map_cutout.jobs import JobManager
from map_cutout.project_store import ProjectStore
from map_cutout.web_app import AppServices, create_app


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


def test_project_save_and_layer_patch(tmp_path):
    app_services = services(tmp_path)
    client = TestClient(create_app(AppConfig(project_root=tmp_path), app_services))
    map_id = app_services.project.state.maps[0].id
    response = client.patch(
        f"/api/maps/{map_id}/layers/original", json={"visible": False})
    assert response.json()["visible"] is False
    assert client.post("/api/projects/save").json()["saved"] is True
    assert app_services.project.manifest_path.exists()

import time

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from map_cutout.config import AppConfig
from map_cutout.domain import BoundingBox, LayerState
from map_cutout.inference import DetectionResult
from map_cutout.jobs import JobManager
from map_cutout.project_store import ProjectStore
from map_cutout.web_app import AppServices, DiskMaskRepository, create_app


class DetectionInference:
    def detect(self, image, prompt, threshold):
        height, width = image.height, image.width
        first = np.zeros((height, width), dtype=bool)
        second = np.zeros((height, width), dtype=bool)
        third = np.zeros((height, width), dtype=bool)
        first[:5, :6] = True
        second[:5, 3:] = True
        third[6:, :4] = True
        return [
            DetectionResult("chair", .9, .95, BoundingBox(0, 0, 6, 5), first),
            DetectionResult("chair", .8, .94, BoundingBox(3, 0, width, 5), second),
            DetectionResult("door", .7, .93, BoundingBox(0, 6, 4, height), third),
        ]


class FullImageInference:
    def detect(self, image, prompt, threshold):
        return [DetectionResult(
            "wall", .9, .9, BoundingBox(0, 0, image.width, image.height),
            np.ones((image.height, image.width), dtype=bool),
        )]


def test_all_detection_results_become_separate_layers_in_one_history_step(tmp_path):
    store = ProjectStore.create(tmp_path / "project")
    image_path = tmp_path / "map.png"
    Image.new("RGB", (12, 10)).save(image_path)
    map_state = store.import_image(image_path)
    services = AppServices(store, DetectionInference(), JobManager(1))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), services))

    job_id = client.post(
        f"/api/maps/{map_state.id}/detect",
        json={"prompt": "chair. door.", "threshold": .4},
    ).json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] == "completed":
            break
        time.sleep(.01)

    assert [layer["name"] for layer in job["result"]] == ["chair1", "chair2", "door1"]
    saved = {
        layer["name"]: np.asarray(Image.open(layer["mask_path"]).convert("L")) > 0
        for layer in job["result"]
    }
    assert saved["chair1"][0, 4]
    assert not saved["chair2"][0, 4]
    assert saved["chair2"][0, 8]
    assert saved["door1"][8, 1]
    overlap = saved["chair1"].astype(np.uint8) + saved["chair2"].astype(np.uint8) + saved["door1"].astype(np.uint8)
    assert int(overlap.max()) == 1
    client.post(f"/api/maps/{map_state.id}/undo")
    layers = client.get(f"/api/maps/{map_state.id}/layers").json()
    assert [layer["kind"] for layer in layers] == ["original"]


def test_new_detection_leaves_out_regions_already_claimed(tmp_path):
    store = ProjectStore.create(tmp_path / "project")
    image_path = tmp_path / "map.png"
    Image.new("RGB", (12, 10)).save(image_path)
    map_state = store.import_image(image_path)
    repository = DiskMaskRepository(store, map_state.id)
    existing = np.zeros((map_state.height, map_state.width), dtype=bool)
    existing[:, :4] = True
    path = repository.save("old", existing)
    map_state.layers.append(LayerState.mask_layer("old", "chair1", "chair", path))
    services = AppServices(store, FullImageInference(), JobManager(1))
    client = TestClient(create_app(AppConfig(project_root=tmp_path), services))

    job_id = client.post(
        f"/api/maps/{map_state.id}/detect",
        json={"prompt": "wall.", "threshold": .4},
    ).json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] == "completed":
            break
        time.sleep(.01)

    assert [layer["name"] for layer in job["result"]] == ["wall1"]
    fresh = np.asarray(Image.open(job["result"][0]["mask_path"]).convert("L")) > 0
    assert not fresh[:, :4].any()
    assert fresh[:, 4:].all()

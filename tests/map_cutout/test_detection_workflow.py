import time

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from map_cutout.config import AppConfig
from map_cutout.domain import BoundingBox
from map_cutout.inference import DetectionResult
from map_cutout.jobs import JobManager
from map_cutout.project_store import ProjectStore
from map_cutout.web_app import AppServices, create_app


class DetectionInference:
    def detect(self, image, prompt, threshold):
        mask = np.ones((image.height, image.width), dtype=bool)
        return [
            DetectionResult("chair", .9, .95, BoundingBox(0, 0, 5, 5), mask),
            DetectionResult("chair", .8, .94, BoundingBox(5, 0, 10, 5), mask),
            DetectionResult("door", .7, .93, BoundingBox(0, 5, 5, 10), mask),
        ]


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
    client.post(f"/api/maps/{map_state.id}/undo")
    layers = client.get(f"/api/maps/{map_state.id}/layers").json()
    assert [layer["kind"] for layer in layers] == ["original"]

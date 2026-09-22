from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .commands import (
    CreateFolderCommand, CreateLayerCommand, DeleteLayerCommand, MergeLayersCommand,
    RenameLayerCommand, SetLayerLockCommand, SetLayerVisibilityCommand,
)
from .config import AppConfig
from .domain import BoundingBox, ExportMode, LayerState
from .exporter import export_layer, unique_windows_name
from .history import HistoryManager
from .inference import InferenceService
from .jobs import JobManager
from .project_store import ProjectStore


class DiskMaskRepository:
    def __init__(self, project: ProjectStore, map_id: str):
        self.directory = project.root / "masks" / map_id
        self.directory.mkdir(parents=True, exist_ok=True)

    def load(self, path):
        return np.asarray(Image.open(path).convert("L")) > 0

    def save(self, layer_id, mask):
        path = self.directory / f"{layer_id}.png"
        Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255, mode="L").save(path)
        return str(path)

    def delete(self, path):
        Path(path).unlink(missing_ok=True)


class _BatchCreate:
    def __init__(self, state, layers):
        self.state, self.layers = state, layers

    def execute(self):
        for layer in self.layers:
            if layer not in self.state.layers:
                self.state.layers.append(layer)
        return self.layers

    def undo(self):
        for layer in self.layers:
            if layer in self.state.layers:
                self.state.layers.remove(layer)


@dataclass
class AppServices:
    project: ProjectStore
    inference: object
    jobs: JobManager
    histories: HistoryManager | None = None

    def __post_init__(self):
        self.histories = self.histories or HistoryManager(limit=50)


def _loopback(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "localhost", "::1"}


def create_app(config: AppConfig | None = None, services: AppServices | None = None) -> FastAPI:
    config = config or AppConfig()
    if not _loopback(config.host):
        raise ValueError("为保护本地文件，仅允许本机地址 127.0.0.1")
    if services is None:
        project = ProjectStore.create(config.project_root / "未命名项目", "未命名项目")
        services = AppServices(project, InferenceService.default(config), JobManager(1))
    app = FastAPI(title="地图抠图工具")
    app.state.services = services

    def map_state(map_id):
        try:
            return services.project.state.map_by_id(map_id)
        except KeyError:
            raise HTTPException(404, "地图不存在")

    def history(map_id):
        return services.histories.for_map(map_id)

    @app.post("/api/projects/new")
    def new_project(payload: dict = Body(...)):
        services.project = ProjectStore.create(Path(payload["path"]), payload.get("name"))
        services.histories.clear()
        return services.project.state.to_dict()

    @app.post("/api/projects/open")
    def open_project(payload: dict = Body(...)):
        services.project = ProjectStore.load(Path(payload["path"]))
        services.histories.clear()
        return services.project.state.to_dict()

    @app.post("/api/projects/save")
    def save_project():
        services.project.save()
        return {"saved": True, "path": str(services.project.manifest_path)}

    @app.post("/api/import/image")
    def import_image(payload: dict = Body(...)):
        return asdict(services.project.import_image(Path(payload["path"])))

    @app.post("/api/import/folder")
    def import_folder(payload: dict = Body(...)):
        return [asdict(item) for item in services.project.import_folder(Path(payload["path"]))]

    @app.get("/api/maps")
    def maps():
        return [asdict(item) for item in services.project.state.maps]

    @app.get("/api/maps/{map_id}/image")
    def map_image(map_id: str):
        return FileResponse(map_state(map_id).source_path)

    @app.get("/api/maps/{map_id}/layers")
    def layers(map_id: str):
        state = map_state(map_id)
        return [asdict(item) for item in state.layers]

    @app.get("/api/maps/{map_id}/layers/{layer_id}/mask")
    def layer_mask(map_id: str, layer_id: str):
        layer = map_state(map_id).layer(layer_id)
        if not layer.mask_path:
            raise HTTPException(404, "此图层没有蒙版")
        return FileResponse(layer.mask_path, media_type="image/png")

    @app.post("/api/maps/{map_id}/detect")
    def detect(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)

        def work():
            with Image.open(state.source_path) as opened:
                image = opened.convert("RGB")
            results = services.inference.detect(image, payload.get("prompt", ""),
                                                float(payload.get("threshold", .4)))
            repository = DiskMaskRepository(services.project, map_id)
            created = []
            for result in results:
                layer_id = uuid4().hex
                path = repository.save(layer_id, result.mask)
                created.append(LayerState.mask_layer(
                    layer_id, state.next_layer_name(result.class_name), result.class_name, path))
            history(map_id).execute(_BatchCreate(state, created))
            services.project.dirty = bool(created) or services.project.dirty
            return [asdict(layer) for layer in created]

        return {"job_id": services.jobs.submit(work)}

    @app.post("/api/maps/{map_id}/segment")
    def segment(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)

        def work():
            with Image.open(state.source_path) as opened:
                image = opened.convert("RGB")
            if "box" in payload:
                mask = services.inference.segment_box(image, BoundingBox(*payload["box"]))
            else:
                box = BoundingBox(*payload["context_box"]) if payload.get("context_box") else None
                mask = services.inference.segment_points(
                    image, payload["points"], payload["labels"], box)
            layer_id = uuid4().hex
            repository = DiskMaskRepository(services.project, map_id)
            layer = LayerState.mask_layer(layer_id, state.next_layer_name(payload.get("name", "object")),
                                          payload.get("name", "object"), repository.save(layer_id, mask))
            history(map_id).execute(CreateLayerCommand(state, layer))
            services.project.dirty = True
            return asdict(layer)

        return {"job_id": services.jobs.submit(work)}

    @app.patch("/api/maps/{map_id}/layers/{layer_id}")
    def patch_layer(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        commands = {"name": RenameLayerCommand, "visible": SetLayerVisibilityCommand,
                    "locked": SetLayerLockCommand}
        for key, command_type in commands.items():
            if key in payload:
                history(map_id).execute(command_type(state, layer_id, payload[key]))
        services.project.dirty = True
        return asdict(state.layer(layer_id))

    @app.delete("/api/maps/{map_id}/layers/{layer_id}")
    def delete_layer(map_id: str, layer_id: str):
        history(map_id).execute(DeleteLayerCommand(map_state(map_id), layer_id))
        services.project.dirty = True
        return {"deleted": True}

    @app.post("/api/maps/{map_id}/layers/merge")
    def merge_layers(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = history(map_id).execute(MergeLayersCommand(
            state, payload["layer_ids"], DiskMaskRepository(services.project, map_id)))
        services.project.dirty = True
        return asdict(layer)

    @app.post("/api/maps/{map_id}/folders")
    def create_folder(map_id: str, payload: dict = Body(...)):
        folder = history(map_id).execute(CreateFolderCommand(map_state(map_id), payload["name"]))
        services.project.dirty = True
        return asdict(folder)

    @app.post("/api/maps/{map_id}/undo")
    def undo(map_id: str):
        changed = history(map_id).undo()
        services.project.dirty = changed or services.project.dirty
        return {"changed": changed}

    @app.post("/api/maps/{map_id}/redo")
    def redo(map_id: str):
        changed = history(map_id).redo()
        services.project.dirty = changed or services.project.dirty
        return {"changed": changed}

    @app.post("/api/export")
    def export(payload: dict = Body(...)):
        state = map_state(payload["map_id"])
        layer = state.layer(payload["layer_id"])
        repository = DiskMaskRepository(services.project, state.id)
        destination = Path(payload.get("directory", services.project.root / "exports"))
        output = unique_windows_name(destination, layer.name)
        with Image.open(state.source_path) as source:
            export_layer(source, repository.load(layer.mask_path), output,
                         ExportMode(payload.get("mode", "tight")))
        return {"path": str(output)}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        try:
            return services.jobs.status(job_id)
        except KeyError:
            raise HTTPException(404, "任务不存在")

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str):
        try:
            return {"cancelled": services.jobs.cancel(job_id)}
        except KeyError:
            raise HTTPException(404, "任务不存在")

    static_dir = Path(__file__).with_name("static")
    tests_dir = Path(__file__).resolve().parents[1] / "tests"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    if tests_dir.exists():
        app.mount("/tests", StaticFiles(directory=tests_dir, html=True), name="tests")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="site")
    return app


def create_test_app() -> FastAPI:
    import tempfile
    root = Path(tempfile.gettempdir()) / "map-cutout-web-test"
    services = AppServices(ProjectStore.create(root, "test"), object(), JobManager(1))
    return create_app(AppConfig(project_root=root), services)

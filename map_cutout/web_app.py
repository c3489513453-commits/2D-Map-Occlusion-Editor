from __future__ import annotations

import shutil
import threading
import math
import base64
import io
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .commands import (
    AssignLayerFolderCommand, CreateFolderCommand, CreateLayerCommand, DeleteFolderCommand,
    DeleteLayerCommand,
    MergeLayersCommand, MoveLayerCommand, RenameLayerCommand, SetLayerLockCommand,
    SetLayerVisibilityCommand, SetOcclusionRegionsCommand, SetOcclusionLinesCommand,
    SetManyOcclusionLinesCommand, SetManyWalkableBoundaryLinesCommand,
    SetWalkableBoundaryLinesCommand,
)
from .config import AppConfig
from .domain import BoundingBox, ExportMode, FolderState, LayerState
from .exporter import BatchExportRequest, BatchExporter, export_layer, unique_windows_name
from .history import HistoryManager
from .inference import InferenceService
from .jobs import JobManager
from .masks import paint_circle, paint_polygon, take_unoccupied, to_mask_image
from .occlusion import baseline_lines_from_mask
from .project_store import ProjectStore, load_startup_project, remember_project
from .walkability import adaptive_walkable_boundary, compose_final_walkable


class DiskMaskRepository:
    def __init__(self, project: ProjectStore, map_id: str):
        self.directory = project.root / "masks" / map_id
        self.directory.mkdir(parents=True, exist_ok=True)

    def load(self, path):
        with Image.open(path) as opened:
            pixels = np.array(opened.convert("L"), dtype=np.uint8, copy=True)
        return pixels > 0

    def save(self, layer_id, mask):
        path = self.directory / f"{layer_id}.png"
        Image.fromarray(to_mask_image(mask), mode="L").save(path)
        return str(path)

    def delete(self, path):
        Path(path).unlink(missing_ok=True)


def occupied_mask(state, repository, skip_layer_id: str | None = None) -> np.ndarray:
    occupied = np.zeros((state.height, state.width), dtype=bool)
    for layer in state.layers:
        if layer.mask_path and layer.id != skip_layer_id:
            occupied |= repository.load(layer.mask_path)
    return occupied


def resource_masks(state, repository) -> list[tuple[LayerState, np.ndarray]]:
    return [
        (layer, repository.load(layer.mask_path))
        for layer in state.layers
        if layer.kind != "original" and layer.mask_path
    ]


def resource_mask_union(state, repository) -> np.ndarray:
    occupied = np.zeros((state.height, state.width), dtype=bool)
    for _, mask in resource_masks(state, repository):
        occupied |= mask
    return occupied


def final_walkable_mask(state, repository) -> np.ndarray:
    manual = [
        repository.load(layer.mask_path)
        for layer in state.walkable_layers
        if layer.mask_path
    ]
    resources = [
        (mask, layer.walkable_boundary_lines)
        for layer, mask in resource_masks(state, repository)
    ]
    if not manual and not resources:
        return np.zeros((state.height, state.width), dtype=bool)
    return compose_final_walkable(manual, resources)


def validated_regions(raw, width: int, height: int) -> list[list[list[float]]]:
    if not isinstance(raw, list):
        raise ValueError("遮挡区域格式不正确")
    normalized = []
    for region in raw:
        if not isinstance(region, list) or len(region) < 3:
            raise ValueError("遮挡区域格式不正确")
        points = []
        for point in region:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("遮挡区域格式不正确")
            x, y = point
            if (isinstance(x, bool) or isinstance(y, bool)
                    or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                    or not math.isfinite(x) or not math.isfinite(y)
                    or not 0 <= x <= width or not 0 <= y <= height):
                raise ValueError("遮挡区域格式不正确")
            points.append([float(x), float(y)])
        if len({(point[0], point[1]) for point in points}) < 3:
            raise ValueError("遮挡区域格式不正确")
        twice_area = sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        if abs(twice_area) < 1e-7:
            raise ValueError("遮挡区域格式不正确")
        normalized.append(points)
    return normalized


def validated_lines(raw, width: int, height: int) -> list[list[list[float]]]:
    if not isinstance(raw, list):
        raise ValueError("底线格式不正确")
    normalized = []
    for line in raw:
        if not isinstance(line, list) or len(line) < 2:
            raise ValueError("底线格式不正确")
        points = []
        for point in line:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("底线格式不正确")
            x, y = point
            if (isinstance(x, bool) or isinstance(y, bool)
                    or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                    or not math.isfinite(x) or not math.isfinite(y)
                    or not 0 <= x <= width or not 0 <= y <= height):
                raise ValueError("底线格式不正确")
            points.append([float(x), float(y)])
        if len({(point[0], point[1]) for point in points}) < 2:
            raise ValueError("底线格式不正确")
        normalized.append(points)
    return normalized


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


class _EditMask:
    def __init__(self, repository, path, before, after):
        self.repository, self.path, self.before, self.after = repository, path, before, after

    def _write(self, mask):
        target = Path(self.path)
        temporary = target.with_name(f"{target.stem}.writing.png")
        Image.fromarray(to_mask_image(mask), mode="L").save(temporary)
        temporary.replace(target)

    def execute(self):
        self._write(self.after)

    def undo(self):
        self._write(self.before)


@dataclass
class AppServices:
    project: ProjectStore
    inference: object
    jobs: JobManager
    histories: HistoryManager | None = None
    previews: dict = field(default_factory=dict)
    mask_locks: dict = field(default_factory=dict)

    def mask_lock(self, key: str):
        return self.mask_locks.setdefault(key, threading.Lock())

    def __post_init__(self):
        self.histories = self.histories or HistoryManager(limit=50)


def _loopback(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "localhost", "::1"}


def create_app(config: AppConfig | None = None, services: AppServices | None = None) -> FastAPI:
    config = config or AppConfig()
    if not _loopback(config.host):
        raise ValueError("为保护本地文件，仅允许本机地址 127.0.0.1")
    if services is None:
        project = load_startup_project(config.project_root)
        services = AppServices(project, InferenceService.default(config), JobManager(1))
    app = FastAPI(title="2D 地图遮挡与行走区域编辑器")
    app.state.services = services

    @app.get("/api/health")
    def health():
        try:
            import torch
            cuda = bool(torch.cuda.is_available())
        except Exception:
            cuda = False
        return {"status": "ok", "cuda": cuda}

    @app.get("/api/dialog/image")
    def choose_image():
        from tkinter import Tk, filedialog
        root = Tk(); root.withdraw(); root.attributes("-topmost", True)
        try:
            path = filedialog.askopenfilename(
                title="选择地图图片",
                filetypes=[("地图图片", "*.png *.jpg *.jpeg"), ("所有文件", "*.*")])
        finally:
            root.destroy()
        return {"path": path or None}

    @app.get("/api/dialog/folder")
    def choose_folder(title: str = "选择文件夹"):
        from tkinter import Tk, filedialog
        root = Tk(); root.withdraw(); root.attributes("-topmost", True)
        try:
            path = filedialog.askdirectory(title=title)
        finally:
            root.destroy()
        return {"path": path or None}

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
        remember_project(config.project_root, services.project)
        services.histories.clear()
        return services.project.state.to_dict()

    @app.post("/api/projects/save")
    def save_project():
        services.project.save()
        remember_project(config.project_root, services.project)
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

    @app.delete("/api/maps/{map_id}")
    def delete_map(map_id: str):
        project = services.project
        removed = map_state(map_id)
        project.state.maps.remove(removed)
        if project.state.current_map_id == map_id:
            project.state.current_map_id = project.state.maps[0].id if project.state.maps else None
        services.histories.forget(map_id)
        shutil.rmtree(project.root / "masks" / map_id, ignore_errors=True)
        (project.root / "thumbnails" / f"{map_id}.jpg").unlink(missing_ok=True)
        project.dirty = True
        return {"deleted": True, "current_map_id": project.state.current_map_id}

    @app.get("/api/maps/{map_id}/image")
    def map_image(map_id: str):
        return FileResponse(map_state(map_id).source_path)

    @app.get("/api/character/info")
    def character_info():
        path = services.project.state.character_path
        return {"available": bool(path and Path(path).is_file()),
                "scale": services.project.state.character_scale}

    @app.get("/api/character")
    def character_image():
        path = services.project.state.character_path
        if not path or not Path(path).is_file(): raise HTTPException(404, "项目还没有测试小人")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.delete("/api/character")
    def delete_character():
        path = services.project.state.character_path
        if path:
            Path(path).unlink(missing_ok=True)
        services.project.state.character_path = None
        services.project.dirty = True
        return {"deleted": bool(path)}

    @app.put("/api/character")
    def save_character(payload: dict = Body(...)):
        try:
            raw = base64.b64decode(payload.get("png_base64", ""), validate=True)
        except Exception:
            raise HTTPException(400, "小人 PNG 数据不正确")
        if not raw or len(raw) > 10 * 1024 * 1024: raise HTTPException(400, "小人 PNG 不能超过 10MB")
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.format != "PNG": raise ValueError
                image = opened.convert("RGBA")
                if not np.asarray(image)[:, :, 3].any(): raise HTTPException(400, "小人图片完全透明")
                assets = services.project.root / "assets"; assets.mkdir(exist_ok=True)
                path = assets / "character.png"; image.save(path)
        except HTTPException: raise
        except Exception: raise HTTPException(400, "无法读取小人 PNG")
        services.project.state.character_path = str(path)
        services.project.state.character_scale = max(.1, min(5.0, float(payload.get("scale", 1))))
        services.project.dirty = True
        return {"saved": True, "scale": services.project.state.character_scale}

    @app.patch("/api/character")
    def patch_character(payload: dict = Body(...)):
        services.project.state.character_scale = max(.1, min(5.0, float(payload.get("scale", 1))))
        services.project.dirty = True
        return {"scale": services.project.state.character_scale}

    @app.get("/api/maps/{map_id}/layers")
    def layers(map_id: str):
        state = map_state(map_id)
        return [asdict(item) for item in state.layers]

    def walkable_layer(state, layer_id: str):
        for layer in state.walkable_layers:
            if layer.id == layer_id:
                return layer
        raise HTTPException(404, "行走图层不存在")

    @app.get("/api/maps/{map_id}/walkable/layers")
    def walkable_layers(map_id: str):
        state = map_state(map_id)
        return {"layers": [asdict(item) for item in state.walkable_layers],
                "folders": [asdict(item) for item in state.walkable_folders]}

    @app.post("/api/maps/{map_id}/walkable/layers")
    def create_walkable_layer(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer_id = uuid4().hex
        name = " ".join(str(payload.get("name") or "新行走图层").split()) or "新行走图层"
        existing = {item.name for item in state.walkable_layers}
        base, number = name, 2
        while name in existing:
            name = f"{base}{number}"; number += 1
        repository = DiskMaskRepository(services.project, map_id)
        path = repository.save(f"walkable-{layer_id}", np.zeros((state.height, state.width), dtype=np.uint8))
        layer = LayerState(layer_id, name, "walkable", mask_path=path)
        state.walkable_layers.insert(0, layer)
        services.project.dirty = True
        return asdict(layer)

    @app.get("/api/maps/{map_id}/walkable/layers/{layer_id}/mask")
    def walkable_layer_mask(map_id: str, layer_id: str):
        layer = walkable_layer(map_state(map_id), layer_id)
        return FileResponse(layer.mask_path, media_type="image/png",
                            headers={"Cache-Control": "no-store"})

    @app.patch("/api/maps/{map_id}/walkable/layers/{layer_id}")
    def patch_walkable_layer(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id); layer = walkable_layer(state, layer_id)
        if "name" in payload: layer.name = " ".join(str(payload["name"]).split()) or layer.name
        if "visible" in payload: layer.visible = bool(payload["visible"])
        if "folder_id" in payload: layer.folder_id = payload["folder_id"]
        if "index" in payload:
            state.walkable_layers.remove(layer)
            state.walkable_layers.insert(max(0, min(int(payload["index"]), len(state.walkable_layers))), layer)
        services.project.dirty = True
        return asdict(layer)

    @app.delete("/api/maps/{map_id}/walkable/layers/{layer_id}")
    def delete_walkable_layer(map_id: str, layer_id: str):
        state = map_state(map_id); layer = walkable_layer(state, layer_id)
        state.walkable_layers.remove(layer)
        if layer.mask_path: Path(layer.mask_path).unlink(missing_ok=True)
        services.project.dirty = True
        return {"deleted": True}

    @app.post("/api/maps/{map_id}/walkable/folders")
    def create_walkable_folder(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        folder = FolderState(uuid4().hex, str(payload.get("name") or "新文件夹"))
        state.walkable_folders.append(folder); services.project.dirty = True
        return asdict(folder)

    @app.delete("/api/maps/{map_id}/walkable/folders/{folder_id}")
    def delete_walkable_folder(map_id: str, folder_id: str):
        state = map_state(map_id)
        folder = next((item for item in state.walkable_folders if item.id == folder_id), None)
        if not folder: raise HTTPException(404, "文件夹不存在")
        state.walkable_folders.remove(folder)
        for layer in state.walkable_layers:
            if layer.folder_id == folder_id: layer.folder_id = None
        services.project.dirty = True
        return {"deleted": True}

    @app.get("/api/maps/{map_id}/layers/{layer_id}/mask")
    def layer_mask(map_id: str, layer_id: str):
        layer = map_state(map_id).layer(layer_id)
        if not layer.mask_path:
            raise HTTPException(404, "此图层没有蒙版")
        return FileResponse(
            layer.mask_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/maps/{map_id}/walkable/mask")
    def walkable_mask(map_id: str):
        state = map_state(map_id)
        if not state.walkable_mask_path:
            raise HTTPException(404, "这张地图还没有行走区域")
        return FileResponse(
            state.walkable_mask_path,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/maps/{map_id}/walkable/final-mask")
    def get_final_walkable_mask(map_id: str):
        state = map_state(map_id)
        repository = DiskMaskRepository(services.project, map_id)
        buffer = io.BytesIO()
        Image.fromarray(to_mask_image(final_walkable_mask(state, repository)), mode="L").save(
            buffer, format="PNG"
        )
        return Response(
            buffer.getvalue(), media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/maps/{map_id}/detect")
    def detect(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)

        def work():
            with Image.open(state.source_path) as opened:
                image = opened.convert("RGB")
            results = services.inference.detect(image, payload.get("prompt", ""),
                                                float(payload.get("threshold", .4)))
            repository = DiskMaskRepository(services.project, map_id)
            occupied = occupied_mask(state, repository)
            created = []
            reserved_names = {layer.name for layer in state.layers}
            for result in results:
                mask = take_unoccupied(result.mask, occupied)
                if not mask.any():
                    continue
                occupied |= mask
                layer_id = uuid4().hex
                path = repository.save(layer_id, mask)
                prefix = (result.class_name.strip().lower().replace(" ", "_") or "object")
                number = 1
                while f"{prefix}{number}" in reserved_names:
                    number += 1
                name = f"{prefix}{number}"
                reserved_names.add(name)
                created.append(LayerState.mask_layer(
                    layer_id, name, result.class_name, path))
            if created:
                history(map_id).execute(_BatchCreate(state, created))
                services.project.dirty = True
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
            repository = DiskMaskRepository(services.project, map_id)
            if payload.get("target_kind") != "walkable":
                mask = take_unoccupied(mask, occupied_mask(state, repository))
            if not mask.any():
                return {"preview_id": None, "empty": True}
            preview_id = uuid4().hex
            services.previews[preview_id] = {"map_id": map_id, "mask": mask,
                                             "name": payload.get("name", "object") or "object"}
            preview_path = services.project.root / "masks" / f"preview-{preview_id}.png"
            Image.fromarray(to_mask_image(mask), mode="L").save(preview_path)
            services.previews[preview_id]["path"] = preview_path
            return {"preview_id": preview_id, "mask_url": f"/api/previews/{preview_id}"}

        return {"job_id": services.jobs.submit(work)}

    @app.post("/api/maps/{map_id}/layers/{layer_id}/segment-add")
    def segment_add(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = state.layer(layer_id)
        if not layer.mask_path:
            raise HTTPException(404, "此图层没有蒙版")
        box = payload.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise HTTPException(400, "请先框选一块区域")

        def work():
            with Image.open(state.source_path) as opened:
                image = opened.convert("RGB")
            recognized = services.inference.segment_box(image, BoundingBox(*box))
            repository = DiskMaskRepository(services.project, map_id)
            with services.mask_lock(f"{map_id}:{layer_id}"):
                before = repository.load(layer.mask_path)
                recognized = np.asarray(recognized, dtype=bool)
                new_pixels = recognized & ~before
                if not new_pixels.any():
                    reason = "empty" if not recognized.any() else "already"
                    return {"added": False, "reason": reason}
                history(map_id).execute(_EditMask(
                    repository, layer.mask_path, before, before | recognized))
            services.project.dirty = True
            return {"added": True}

        return {"job_id": services.jobs.submit(work)}

    @app.post("/api/maps/{map_id}/walkable/layers/{layer_id}/segment-add")
    def segment_add_walkable(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = walkable_layer(state, layer_id)
        box = payload.get("box")
        if not isinstance(box, list) or len(box) != 4:
            raise HTTPException(400, "请先框选一块区域")

        def work():
            with Image.open(state.source_path) as opened:
                image = opened.convert("RGB")
            recognized = np.asarray(
                services.inference.segment_box(image, BoundingBox(*box)), dtype=bool)
            repository = DiskMaskRepository(services.project, map_id)
            with services.mask_lock(f"{map_id}:walkable:{layer_id}"):
                before = repository.load(layer.mask_path)
                recognized &= ~resource_mask_union(state, repository)
                if not (recognized & ~before).any():
                    return {"added": False,
                            "reason": "empty" if not recognized.any() else "already"}
                history(map_id).execute(_EditMask(
                    repository, layer.mask_path, before, before | recognized))
            services.project.dirty = True
            return {"added": True}

        return {"job_id": services.jobs.submit(work)}

    @app.get("/api/previews/{preview_id}")
    def preview_mask(preview_id: str):
        preview = services.previews.get(preview_id)
        if not preview:
            raise HTTPException(404, "预览不存在")
        return FileResponse(preview["path"], media_type="image/png")

    @app.post("/api/maps/{map_id}/segment/commit")
    def commit_segment(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        preview = services.previews.pop(payload["preview_id"], None)
        if not preview or preview["map_id"] != map_id:
            raise HTTPException(404, "预览不存在或不属于当前地图")
        layer_id = uuid4().hex
        repository = DiskMaskRepository(services.project, map_id)
        mask = take_unoccupied(preview["mask"], occupied_mask(state, repository))
        if not mask.any():
            Path(preview["path"]).unlink(missing_ok=True)
            raise HTTPException(409, "这块地方已经有蒙版了")
        name = payload.get("name") or preview["name"] or "object"
        layer = LayerState.mask_layer(layer_id, state.next_layer_name(name), name,
                                      repository.save(layer_id, mask))
        history(map_id).execute(CreateLayerCommand(state, layer))
        Path(preview["path"]).unlink(missing_ok=True)
        services.project.dirty = True
        return asdict(layer)

    @app.delete("/api/previews/{preview_id}")
    def discard_preview(preview_id: str):
        preview = services.previews.pop(preview_id, None)
        if preview:
            Path(preview["path"]).unlink(missing_ok=True)
        return {"deleted": bool(preview)}

    @app.post("/api/maps/{map_id}/layers/{layer_id}/paint")
    def paint_layer(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = state.layer(layer_id)
        repository = DiskMaskRepository(services.project, map_id)
        with services.mask_lock(f"{map_id}:{layer_id}"):
            before = repository.load(layer.mask_path)
            after = before.copy()
            points = payload.get("points", [])
            if payload.get("shape") == "polygon":
                after = paint_polygon(after, points, int(payload.get("value", 255)))
            else:
                for start, end in zip(points, points[1:] or points):
                    distance = max(abs(end[0]-start[0]), abs(end[1]-start[1]), 1)
                    for step in range(int(distance)+1):
                        ratio = step / distance
                        after = paint_circle(after, start[0]+(end[0]-start[0])*ratio,
                                             start[1]+(end[1]-start[1])*ratio,
                                             float(payload.get("radius", 10)), int(payload.get("value", 255)))
            history(map_id).execute(_EditMask(repository, layer.mask_path, before, after))
        services.project.dirty = True
        return {"updated": True}

    @app.post("/api/maps/{map_id}/walkable/layers/{layer_id}/paint")
    def paint_walkable(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = walkable_layer(state, layer_id)
        repository = DiskMaskRepository(services.project, map_id)
        with services.mask_lock(f"{map_id}:walkable:{layer_id}"):
            before = repository.load(layer.mask_path)
            after = before.copy()
            points = payload.get("points", [])
            if payload.get("shape") == "polygon":
                after = paint_polygon(after, points, int(payload.get("value", 255)))
            else:
                for start, end in zip(points, points[1:] or points):
                    distance = max(abs(end[0]-start[0]), abs(end[1]-start[1]), 1)
                    for step in range(int(distance)+1):
                        ratio = step / distance
                        after = paint_circle(after, start[0]+(end[0]-start[0])*ratio,
                                             start[1]+(end[1]-start[1])*ratio,
                                             float(payload.get("radius", 10)), int(payload.get("value", 255)))
            after &= ~resource_mask_union(state, repository)
            history(map_id).execute(_EditMask(
                repository, layer.mask_path, before, after))
        services.project.dirty = True
        return {"updated": True}

    @app.patch("/api/maps/{map_id}/layers/{layer_id}")
    def patch_layer(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        commands = {"name": RenameLayerCommand, "visible": SetLayerVisibilityCommand,
                    "locked": SetLayerLockCommand}
        for key, command_type in commands.items():
            if key in payload:
                history(map_id).execute(command_type(state, layer_id, payload[key]))
        if "folder_id" in payload:
            history(map_id).execute(AssignLayerFolderCommand(state, layer_id, payload["folder_id"]))
        if "index" in payload:
            history(map_id).execute(MoveLayerCommand(state, layer_id, int(payload["index"])))
        services.project.dirty = True
        return asdict(state.layer(layer_id))

    @app.put("/api/maps/{map_id}/layers/{layer_id}/occlusion-regions")
    def put_occlusion_regions(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        try:
            layer = state.layer(layer_id)
        except KeyError:
            raise HTTPException(404, "图层不存在")
        if layer.kind == "original" or not layer.mask_path:
            raise HTTPException(400, "只有蒙版图层可以绘制遮挡区域")
        try:
            regions = validated_regions(payload.get("regions"), state.width, state.height)
        except (TypeError, ValueError):
            raise HTTPException(400, "遮挡区域格式不正确")
        history(map_id).execute(SetOcclusionRegionsCommand(state, layer_id, regions))
        services.project.dirty = True
        return asdict(layer)

    @app.put("/api/maps/{map_id}/layers/{layer_id}/walkable-boundary-lines")
    def put_walkable_boundary_lines(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        try:
            layer = state.layer(layer_id)
        except KeyError:
            raise HTTPException(404, "图层不存在")
        if layer.kind == "original" or not layer.mask_path:
            raise HTTPException(400, "只有蒙版图层可以编辑可走边界")
        try:
            lines = validated_lines(payload.get("lines"), state.width, state.height)
        except (TypeError, ValueError):
            raise HTTPException(400, "可走边界格式不正确")
        history(map_id).execute(SetWalkableBoundaryLinesCommand(state, layer_id, lines))
        services.project.dirty = True
        return asdict(layer)

    @app.post("/api/maps/{map_id}/walkable-boundary-lines/auto")
    def auto_walkable_boundary_lines(map_id: str):
        state = map_state(map_id)
        repository = DiskMaskRepository(services.project, map_id)
        candidates = [
            layer for layer in state.layers
            if layer.kind != "original" and layer.mask_path
        ]
        skipped = sum(1 for layer in candidates if layer.walkable_boundary_lines)
        changes = []
        for layer in candidates:
            if layer.walkable_boundary_lines:
                continue
            line = adaptive_walkable_boundary(repository.load(layer.mask_path))
            if line:
                changes.append((layer, [line]))
        if changes:
            history(map_id).execute(SetManyWalkableBoundaryLinesCommand(changes))
            services.project.dirty = True
        return {
            "created": len(changes),
            "skipped": skipped,
        }

    @app.post("/api/maps/{map_id}/walkable/layers/{layer_id}/segment-commit")
    def commit_segment_walkable(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer = walkable_layer(state, layer_id)
        preview = services.previews.pop(payload.get("preview_id"), None)
        if not preview or preview["map_id"] != map_id:
            raise HTTPException(404, "预览不存在或不属于当前地图")
        repository = DiskMaskRepository(services.project, map_id)
        with services.mask_lock(f"{map_id}:walkable:{layer_id}"):
            before = repository.load(layer.mask_path)
            after = before | np.asarray(preview["mask"], dtype=bool)
            after &= ~resource_mask_union(state, repository)
            history(map_id).execute(_EditMask(
                repository, layer.mask_path, before, after))
        Path(preview["path"]).unlink(missing_ok=True)
        services.project.dirty = True
        return asdict(layer)

    @app.put("/api/maps/{map_id}/layers/{layer_id}/occlusion-lines")
    def put_occlusion_lines(map_id: str, layer_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        try:
            layer = state.layer(layer_id)
        except KeyError:
            raise HTTPException(404, "图层不存在")
        if layer.kind == "original" or not layer.mask_path:
            raise HTTPException(400, "只有蒙版图层可以编辑底线")
        try:
            lines = validated_lines(payload.get("lines"), state.width, state.height)
        except (TypeError, ValueError):
            raise HTTPException(400, "底线格式不正确")
        history(map_id).execute(SetOcclusionLinesCommand(state, layer_id, lines))
        services.project.dirty = True
        return asdict(layer)

    @app.post("/api/maps/{map_id}/occlusion-lines/auto")
    def auto_occlusion_lines(map_id: str):
        state = map_state(map_id)
        changes = []
        for layer in state.layers:
            if layer.kind == "original" or not layer.mask_path or layer.occlusion_lines:
                continue
            mask = np.asarray(Image.open(layer.mask_path).convert("L"))
            lines = baseline_lines_from_mask(mask)
            if lines:
                changes.append((layer, lines))
        if changes:
            history(map_id).execute(SetManyOcclusionLinesCommand(changes))
            services.project.dirty = True
        return {"created": len(changes), "skipped": sum(
            1 for layer in state.layers if layer.mask_path and layer.occlusion_lines
        )}

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

    @app.post("/api/maps/{map_id}/layers")
    def create_layer(map_id: str, payload: dict = Body(...)):
        state = map_state(map_id)
        layer_id = uuid4().hex
        name = state.unique_layer_name(str(payload.get("name") or "新图层"))
        repository = DiskMaskRepository(services.project, map_id)
        mask = np.zeros((state.height, state.width), dtype=np.uint8)
        layer = LayerState.mask_layer(layer_id, name, name, repository.save(layer_id, mask))
        history(map_id).execute(CreateLayerCommand(state, layer, index=0))
        services.project.dirty = True
        return asdict(layer)

    @app.post("/api/maps/{map_id}/folders")
    def create_folder(map_id: str, payload: dict = Body(...)):
        folder = history(map_id).execute(CreateFolderCommand(map_state(map_id), payload["name"]))
        services.project.dirty = True
        return asdict(folder)

    @app.delete("/api/maps/{map_id}/folders/{folder_id}")
    def delete_folder(map_id: str, folder_id: str):
        try:
            history(map_id).execute(DeleteFolderCommand(map_state(map_id), folder_id))
        except StopIteration:
            raise HTTPException(404, "文件夹不存在")
        services.project.dirty = True
        return {"deleted": True}

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
        destination = Path(payload.get("output_dir") or services.project.root / "exports")
        map_ids = payload.get("map_ids")
        if not map_ids and payload.get("map_id"):
            map_ids = [payload["map_id"]]
        layer_ids = payload.get("layer_ids")
        if not layer_ids and payload.get("layer_id"):
            layer_ids = [payload["layer_id"]]
        report = BatchExporter(services.project.state).export(BatchExportRequest(
            output_dir=destination, scope=payload.get("scope", "map"), map_ids=map_ids,
            layer_ids=layer_ids, mode=payload.get("mode", "tight"),
            include_hidden=bool(payload.get("include_hidden", True)),
            preserve_folders=bool(payload.get("preserve_folders", False)),
            include_occlusion=bool(payload.get("include_occlusion", False))))
        return {"exported": [str(path) for path in report.exported],
                "skipped": report.skipped, "failures": report.failures,
                "occlusion_manifests": [str(path) for path in report.occlusion_manifests],
                "output_dir": str(destination)}

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

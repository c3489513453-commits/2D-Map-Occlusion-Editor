from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .domain import ExportMode
from .domain import ProjectState
from .masks import mask_bounds


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}"
    for prefix in ("COM", "LPT")
    for number in range(1, 10)
}


def safe_windows_stem(name: str) -> str:
    stem = _ILLEGAL.sub("_", name).rstrip(" .") or "untitled"
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    return stem


def unique_windows_name(directory: Path, name: str, suffix: str = ".png") -> Path:
    directory = Path(directory)
    stem = safe_windows_stem(name)
    candidate = directory / f"{stem}{suffix}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def export_layer(
    source: Image.Image,
    mask: np.ndarray,
    output: Path,
    mode: ExportMode,
) -> Path:
    if mask.shape != (source.height, source.width):
        raise ValueError("蒙版尺寸与源图片不一致")
    rgba = source.convert("RGBA")
    alpha = (np.asarray(mask) > 0).astype(np.uint8) * 255
    rgba.putalpha(Image.fromarray(alpha, mode="L"))
    if mode is ExportMode.TIGHT:
        box = mask_bounds(mask)
        rgba = rgba.crop((box.x1, box.y1, box.x2, box.y2))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(output, format="PNG")
    return output


@dataclass
class BatchExportRequest:
    output_dir: Path
    scope: str = "map"
    map_ids: list[str] | None = None
    layer_ids: list[str] | None = None
    mode: str | ExportMode = ExportMode.TIGHT
    include_hidden: bool = True
    preserve_folders: bool = False
    include_occlusion: bool = False


@dataclass
class BatchExportReport:
    exported: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    occlusion_manifests: list[Path] = field(default_factory=list)


class BatchExporter:
    def __init__(self, project: ProjectState):
        self.project = project

    def export(self, request: BatchExportRequest) -> BatchExportReport:
        report = BatchExportReport()
        output_root = Path(request.output_dir)
        mode = request.mode if isinstance(request.mode, ExportMode) else ExportMode(request.mode)
        maps = [item for item in self.project.maps
                if not request.map_ids or item.id in request.map_ids]
        for map_state in maps:
            map_dir = output_root
            if len(maps) > 1:
                map_dir = output_root / safe_windows_stem(Path(map_state.source_path).stem)
            folders = {folder.id: folder for folder in map_state.folders}
            try:
                with Image.open(map_state.source_path) as opened:
                    source = opened.convert("RGB")
            except FileNotFoundError:
                report.failures.append({
                    "map_id": map_state.id,
                    "layer_id": "source",
                    "name": Path(map_state.source_path).name,
                    "reason": f"原图文件不存在：{map_state.source_path}",
                })
                continue
            except Exception as exc:
                report.failures.append({
                    "map_id": map_state.id,
                    "layer_id": "source",
                    "name": Path(map_state.source_path).name,
                    "reason": f"无法读取原图：{exc}",
                })
                continue
            # A logic package already exports the required full-size occluders.
            # Do not also emit the regular transparent assets at the output root.
            if not request.include_occlusion:
                layers_for_regular_export = map_state.layers
            else:
                layers_for_regular_export = []
            for layer in layers_for_regular_export:
                if request.layer_ids and layer.id not in request.layer_ids:
                    continue
                if request.scope == "visible" and not layer.visible:
                    report.skipped.append(layer.name)
                    continue
                if not request.include_hidden and not layer.visible:
                    report.skipped.append(layer.name)
                    continue
                directory = map_dir
                if request.preserve_folders and layer.folder_id in folders:
                    directory = map_dir / safe_windows_stem(folders[layer.folder_id].name)
                try:
                    output = unique_windows_name(directory, layer.name)
                    if layer.kind == "original":
                        output.parent.mkdir(parents=True, exist_ok=True)
                        source.save(output, format="PNG")
                    elif layer.mask_path:
                        mask = np.asarray(Image.open(layer.mask_path).convert("L")) > 0
                        export_layer(source, mask, output, mode)
                    else:
                        report.skipped.append(layer.name)
                        continue
                    report.exported.append(output)
                except Exception as exc:
                    report.failures.append({"map_id": map_state.id, "layer_id": layer.id,
                                            "name": layer.name, "reason": str(exc)})
            if request.include_occlusion:
                self._export_occlusion_package(map_state, output_root, request, report)
        return report

    def _export_occlusion_package(
        self,
        map_state,
        output_root: Path,
        request: BatchExportRequest,
        report: BatchExportReport,
    ) -> None:
        package_dir = output_root / safe_windows_stem(Path(map_state.source_path).stem)
        occluder_dir = package_dir / "occluders"
        entries = []
        with Image.open(map_state.source_path) as opened:
            source = opened.convert("RGB")
        package_dir.mkdir(parents=True, exist_ok=True)
        map_output = package_dir / "map.png"
        source.save(map_output, format="PNG")
        report.exported.append(map_output)
        for layer in map_state.layers:
            if layer.kind == "original" or not layer.mask_path or not layer.occlusion_lines:
                continue
            if request.layer_ids and layer.id not in request.layer_ids:
                continue
            if request.scope == "visible" and not layer.visible:
                continue
            if not request.include_hidden and not layer.visible:
                continue
            try:
                output = unique_windows_name(occluder_dir, layer.name)
                mask = np.asarray(Image.open(layer.mask_path).convert("L")) > 0
                export_layer(source, mask, output, ExportMode.FULL_SIZE)
                report.exported.append(output)
                entries.append({
                    "id": layer.id,
                    "name": layer.name,
                    "image": output.relative_to(package_dir).as_posix(),
                    "imageMode": "full_size",
                    "lines": layer.occlusion_lines,
                })
            except Exception as exc:
                report.failures.append({"map_id": map_state.id, "layer_id": layer.id,
                                        "name": layer.name, "reason": str(exc)})
        walkable_name = None
        walkable_layers = [layer for layer in map_state.walkable_layers
                           if layer.mask_path and (request.include_hidden or layer.visible)]
        if walkable_layers:
            try:
                package_dir.mkdir(parents=True, exist_ok=True)
                walkable_output = package_dir / "walkable.png"
                combined = np.zeros((map_state.height, map_state.width), dtype=bool)
                for layer in walkable_layers:
                    combined |= np.asarray(Image.open(layer.mask_path).convert("L")) > 0
                Image.fromarray((combined * 255).astype(np.uint8), mode="L").save(walkable_output)
                report.exported.append(walkable_output)
                walkable_name = walkable_output.name
            except Exception as exc:
                report.failures.append({"map_id": map_state.id, "layer_id": "walkable",
                                        "name": "行走区域", "reason": str(exc)})
        if not entries and not walkable_name:
            return
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = package_dir / "occlusion.json"
        manifest_path.write_text(json.dumps({
            "version": 2,
            "map": {
                "width": map_state.width,
                "height": map_state.height,
                "coordinateOrigin": "top-left",
                "image": map_output.name,
            },
            "walkableMask": walkable_name,
            "walkable": ({
                "mask": walkable_name,
                "rule": "character_footprint_must_be_inside",
                "layers": [{"id": layer.id, "name": layer.name}
                           for layer in walkable_layers],
            } if walkable_name else None),
            "occluders": entries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        report.exported.append(manifest_path)
        report.occlusion_manifests.append(manifest_path)

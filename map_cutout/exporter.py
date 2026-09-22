from __future__ import annotations

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
    rgba.putalpha(Image.fromarray(mask.astype(np.uint8), mode="L"))
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


@dataclass
class BatchExportReport:
    exported: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


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
            with Image.open(map_state.source_path) as opened:
                source = opened.convert("RGB")
            for layer in map_state.layers:
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
        return report

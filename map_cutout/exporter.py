from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from .domain import ExportMode
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

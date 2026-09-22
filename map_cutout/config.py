from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AppConfig:
    project_root: Path = field(
        default_factory=lambda: Path(
            os.getenv("MAP_CUTOUT_PROJECT_ROOT", r"D:\06\剧本\地图抠图\项目输出")
        )
    )
    sam_checkpoint: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "MAP_CUTOUT_SAM_CHECKPOINT",
                _repository_root() / "checkpoints" / "sam2.1_hiera_small.pt",
            )
        )
    )
    sam_config: str = field(
        default_factory=lambda: os.getenv(
            "MAP_CUTOUT_SAM_CONFIG", "configs/sam2.1/sam2.1_hiera_s.yaml"
        )
    )
    grounding_model: str = field(
        default_factory=lambda: os.getenv(
            "MAP_CUTOUT_GROUNDING_MODEL", "IDEA-Research/grounding-dino-tiny"
        )
    )
    host: str = field(default_factory=lambda: os.getenv("MAP_CUTOUT_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("MAP_CUTOUT_PORT", "7860")))


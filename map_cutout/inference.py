from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol, Sequence

import numpy as np
from PIL import Image

from .config import AppConfig
from .domain import BoundingBox


def normalize_prompt(prompt: str) -> str:
    phrases = [part.strip().lower() for part in re.split(r"[.,;，；。]+", prompt)]
    normalized = [part for part in phrases if part]
    return ". ".join(normalized) + ("." if normalized else "")


@dataclass(frozen=True)
class DetectionResult:
    class_name: str
    confidence: float
    sam_score: float
    box: BoundingBox
    mask: np.ndarray


class Detector(Protocol):
    def detect(self, image: Image.Image, prompt: str, threshold: float) -> list[dict]: ...


class Segmenter(Protocol):
    def segment(self, image: Image.Image, *, boxes=None, points=None, labels=None): ...


class _HuggingFaceDetector:
    def __init__(self, model_id: str, device: str):
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)

    def detect(self, image: Image.Image, prompt: str, threshold: float) -> list[dict]:
        import torch

        inputs = self.processor(images=image, text=prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, box_threshold=threshold, text_threshold=0.3,
            target_sizes=[image.size[::-1]],
        )[0]
        boxes = result["boxes"].detach().cpu().numpy()
        scores = result["scores"].detach().cpu().numpy()
        return [{"label": label, "score": float(score), "box": box.tolist()}
                for label, score, box in zip(result["labels"], scores, boxes)]


class _SamSegmenter:
    def __init__(self, config: AppConfig, device: str):
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        model = build_sam2(config.sam_config, str(config.sam_checkpoint), device=device)
        self.predictor = SAM2ImagePredictor(model)

    def segment(self, image, *, boxes=None, points=None, labels=None):
        self.predictor.set_image(np.asarray(image.convert("RGB")))
        box_array = None if boxes is None else np.asarray(boxes, dtype=np.float32)
        if points is not None and box_array is not None and len(box_array) == 1:
            box_array = box_array[0]
        masks, scores, _ = self.predictor.predict(
            point_coords=None if points is None else np.asarray(points, dtype=np.float32),
            point_labels=None if labels is None else np.asarray(labels, dtype=np.int32),
            box=box_array, multimask_output=False,
        )
        return masks, scores


class InferenceService:
    def __init__(self, detector: Detector | None = None, segmenter: Segmenter | None = None,
                 *, config: AppConfig | None = None, force_cpu: bool = False):
        self._detector = detector
        self._segmenter = segmenter
        self.config = config or AppConfig()
        self.force_cpu = force_cpu

    @classmethod
    def default(cls, config: AppConfig | None = None, *, force_cpu: bool = False):
        return cls(config=config, force_cpu=force_cpu)

    def _ensure_loaded(self) -> None:
        if self._detector is not None and self._segmenter is not None:
            return
        import torch

        device = "cuda" if torch.cuda.is_available() and not self.force_cpu else "cpu"
        if self._detector is None:
            self._detector = _HuggingFaceDetector(self.config.grounding_model, device)
        if self._segmenter is None:
            self._segmenter = _SamSegmenter(self.config, device)

    @staticmethod
    def _mask_and_score(masks, scores, index: int = 0):
        mask_array = np.asarray(masks)
        if mask_array.ndim == 4:
            mask_array = mask_array[:, 0]
        if mask_array.ndim == 3:
            mask_array = mask_array[index if mask_array.shape[0] > index else 0]
        score_array = np.asarray(scores).reshape(-1)
        score = float(score_array[index if score_array.size > index else 0])
        return mask_array.astype(bool), score

    def detect(self, image: Image.Image, prompt: str, threshold: float = 0.4):
        self._ensure_loaded()
        detections = self._detector.detect(image, normalize_prompt(prompt), threshold)
        if not detections:
            return []
        boxes = [item["box"] for item in detections]
        masks, sam_scores = self._segmenter.segment(image, boxes=boxes)
        results = []
        for index, item in enumerate(detections):
            mask, sam_score = self._mask_and_score(masks, sam_scores, index)
            x1, y1, x2, y2 = (int(round(value)) for value in item["box"])
            results.append(DetectionResult(str(item["label"]), float(item["score"]), sam_score,
                                           BoundingBox(x1, y1, x2, y2), mask))
        return results

    def segment_box(self, image: Image.Image, box: BoundingBox) -> np.ndarray:
        self._ensure_loaded()
        masks, scores = self._segmenter.segment(
            image, boxes=[[box.x1, box.y1, box.x2, box.y2]])
        return self._mask_and_score(masks, scores)[0]

    def segment_points(self, image: Image.Image, points: Sequence[Sequence[float]],
                       labels: Sequence[int], box: BoundingBox | None = None) -> np.ndarray:
        self._ensure_loaded()
        boxes = None if box is None else [[box.x1, box.y1, box.x2, box.y2]]
        masks, scores = self._segmenter.segment(
            image, boxes=boxes, points=points, labels=labels)
        return self._mask_and_score(masks, scores)[0]

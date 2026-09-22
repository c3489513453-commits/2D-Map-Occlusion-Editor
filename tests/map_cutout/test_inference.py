from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from map_cutout.domain import BoundingBox
from map_cutout.inference import InferenceService, normalize_prompt


class FakeDetector:
    def __init__(self, detections=None):
        self.detections = detections or []
        self.calls = []

    def detect(self, image, prompt, threshold):
        self.calls.append((image.size, prompt, threshold))
        return self.detections


class FakeSegmenter:
    def __init__(self):
        self.calls = []

    def segment(self, image, *, boxes=None, points=None, labels=None):
        self.calls.append(
            {"boxes": boxes, "points": points, "labels": labels}
        )
        width, height = image.size
        count = len(boxes) if boxes is not None else 1
        masks = np.zeros((count, height, width), dtype=np.float32)
        masks[:, 4:20, 5:25] = 1
        return masks, np.full(count, 0.95, dtype=np.float32)


def test_prompt_is_normalized_to_lowercase_period_terminated_phrases():
    assert normalize_prompt(" Chair, stone wall ; DOOR ") == "chair. stone wall. door."


def test_detection_masks_are_boolean_original_size():
    detector = FakeDetector(
        [{"label": "chair", "score": 0.88, "box": [5, 4, 25, 20]}]
    )
    segmenter = FakeSegmenter()
    service = InferenceService(detector=detector, segmenter=segmenter)

    result = service.detect(Image.new("RGB", (64, 48)), " Chair ", 0.4)

    assert detector.calls[0][1] == "chair."
    assert result[0].mask.dtype == np.bool_
    assert result[0].mask.shape == (48, 64)
    assert result[0].class_name == "chair"
    assert result[0].box == BoundingBox(5, 4, 25, 20)
    assert result[0].sam_score == pytest.approx(0.95)


def test_no_detections_returns_empty_without_segmenting():
    segmenter = FakeSegmenter()
    service = InferenceService(detector=FakeDetector(), segmenter=segmenter)

    assert service.detect(Image.new("RGB", (32, 24)), "wall", 0.4) == []
    assert segmenter.calls == []


def test_box_and_point_prompts_return_boolean_masks():
    segmenter = FakeSegmenter()
    service = InferenceService(detector=FakeDetector(), segmenter=segmenter)
    image = Image.new("RGB", (40, 30))

    box_mask = service.segment_box(image, BoundingBox(1, 2, 20, 22))
    point_mask = service.segment_points(
        image, [(7, 8), (9, 10)], [1, 0], BoundingBox(1, 2, 20, 22)
    )

    assert box_mask.dtype == np.bool_
    assert point_mask.shape == (30, 40)
    assert segmenter.calls[0]["boxes"] == [[1, 2, 20, 22]]
    assert segmenter.calls[1]["points"] == [(7, 8), (9, 10)]
    assert segmenter.calls[1]["labels"] == [1, 0]

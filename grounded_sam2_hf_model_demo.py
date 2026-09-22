from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pycocotools.mask as mask_util
import supervision as sv
from PIL import Image
from supervision.draw.color import ColorPalette

from map_cutout.config import AppConfig
from map_cutout.inference import InferenceService
from utils.supervision_utils import CUSTOM_COLOR_MAP


def single_mask_to_rle(mask):
    rle = mask_util.encode(np.array(mask[:, :, None], order="F", dtype="uint8"))[0]
    rle["counts"] = rle["counts"].decode("utf-8")
    return rle


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grounding-model", default="IDEA-Research/grounding-dino-tiny")
    parser.add_argument("--text-prompt", default="car. tire.")
    parser.add_argument("--img-path", default="notebooks/images/truck.jpg")
    parser.add_argument("--sam2-checkpoint", default="./checkpoints/sam2.1_hiera_small.pt")
    parser.add_argument("--sam2-model-config", default="configs/sam2.1/sam2.1_hiera_s.yaml")
    parser.add_argument("--output-dir", default="outputs/grounded_sam2_hf_demo")
    parser.add_argument("--no-dump-json", action="store_true")
    parser.add_argument("--force-cpu", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(args.img_path).convert("RGB")
    config = replace(
        AppConfig(), grounding_model=args.grounding_model,
        sam_checkpoint=Path(args.sam2_checkpoint), sam_config=args.sam2_model_config)
    results = InferenceService.default(config, force_cpu=args.force_cpu).detect(
        image, args.text_prompt, 0.4)

    boxes = np.asarray([[r.box.x1, r.box.y1, r.box.x2, r.box.y2] for r in results],
                       dtype=np.float32).reshape(-1, 4)
    masks = np.asarray([r.mask for r in results], dtype=bool)
    labels = [f"{r.class_name} {r.confidence:.2f}" for r in results]
    detections = sv.Detections(xyxy=boxes, mask=masks if len(masks) else None,
                               class_id=np.arange(len(results)))
    palette = ColorPalette.from_hex(CUSTOM_COLOR_MAP)
    frame = np.asarray(image).copy()
    frame = sv.BoxAnnotator(color=palette).annotate(frame, detections)
    frame = sv.LabelAnnotator(color=palette).annotate(frame, detections, labels=labels)
    Image.fromarray(frame).save(output_dir / "groundingdino_annotated_image.jpg")
    if results:
        frame = sv.MaskAnnotator(color=palette).annotate(frame, detections)
    Image.fromarray(frame).save(output_dir / "grounded_sam2_annotated_image_with_mask.jpg")

    if not args.no_dump_json:
        payload = {
            "image_path": args.img_path,
            "annotations": [{"class_name": r.class_name,
                             "bbox": [r.box.x1, r.box.y1, r.box.x2, r.box.y2],
                             "segmentation": single_mask_to_rle(r.mask),
                             "score": r.sam_score} for r in results],
            "box_format": "xyxy", "img_width": image.width, "img_height": image.height,
        }
        (output_dir / "grounded_sam2_hf_model_demo_results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")


if __name__ == "__main__":
    main()

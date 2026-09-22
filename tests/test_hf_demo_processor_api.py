from pathlib import Path


def test_demo_uses_shared_inference_service():
    source = Path("grounded_sam2_hf_model_demo.py").read_text(encoding="utf-8")
    assert "from map_cutout.inference import InferenceService" in source
    assert "post_process_grounded_object_detection" not in source
    assert "cv2.imread" not in source


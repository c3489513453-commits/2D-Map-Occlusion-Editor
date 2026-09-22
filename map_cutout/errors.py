from __future__ import annotations


def chinese_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "out of memory" in lowered or "cuda" in lowered and "memory" in lowered:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        return "显存不足，识别未写入任何图层。请缩小图片后重试，或降低一次识别的目标数量。"
    if isinstance(exc, FileNotFoundError):
        return f"找不到文件：{text}"
    return f"操作失败：{text or exc.__class__.__name__}"


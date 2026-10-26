"""模型封装：深度估计（F1）、开放词汇检测（F2）、收纳规则归纳（F3，可选 LLM）。

全部懒加载 + 单例；模型权重来自本机 HF 缓存（离线）。
"""
import io
import os
import threading

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import torch
from PIL import Image
from transformers import (
    AutoImageProcessor, AutoModelForDepthEstimation,
    AutoProcessor, AutoModelForZeroShotObjectDetection,
)

DEPTH_ID = "depth-anything/Depth-Anything-V2-Small-hf"
GDINO_ID = "IDEA-Research/grounding-dino-tiny"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QWEN_DIR = os.path.join(ROOT, "models", "qwen2.5-3b")

DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
_lock = threading.Lock()
_cache = {}

# 粗估距离假设（与 scripts/week1_photos_demo.py 一致，阶段 2 换成标定值）
F_PX_640 = 212.0
CAM_H = 0.25


def _depth_model():
    with _lock:
        if "depth" not in _cache:
            proc = AutoImageProcessor.from_pretrained(DEPTH_ID)
            model = AutoModelForDepthEstimation.from_pretrained(DEPTH_ID).to(DEVICE).eval()
            _cache["depth"] = (proc, model)
        return _cache["depth"]


def _gdino_model():
    with _lock:
        if "gdino" not in _cache:
            proc = AutoProcessor.from_pretrained(GDINO_ID)
            model = AutoModelForZeroShotObjectDetection.from_pretrained(GDINO_ID).to(DEVICE).eval()
            _cache["gdino"] = (proc, model)
        return _cache["gdino"]


def _pil(jpeg_bytes):
    return Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")


def depth_map(jpeg_bytes, colorize=True):
    """返回 (vis_png_bytes, depth_np)。vis 用 INFERNO 配色（亮=近）。"""
    proc, model = _depth_model()
    img = _pil(jpeg_bytes)
    w, h = img.size
    inp = proc(images=img, return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        out = model(**inp)
    d = torch.nn.functional.interpolate(
        out.predicted_depth[:, None].float(), (h, w), mode="bilinear", align_corners=True
    )[0, 0].cpu().numpy()
    if not colorize:
        return None, d
    import cv2
    norm = (d - d.min()) / (d.max() - d.min() + 1e-6)
    vis = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    ok, buf = cv2.imencode(".png", vis)
    return (buf.tobytes() if ok else None), d


def rough_distance_m(row_px, img_h):
    dv = row_px - img_h / 2.0
    if dv <= 10:
        return None
    f = F_PX_640 * (img_h / 360.0)
    return round(f * CAM_H / dv, 2)


def detect(jpeg_bytes, text, box_threshold=0.3, text_threshold=0.25):
    """开放词汇检测：text 为英文短语（多个用 ' . ' 连接）。返回框/分数/粗估距离。"""
    proc, model = _gdino_model()
    img = _pil(jpeg_bytes)
    w, h = img.size
    inp = proc(images=img, text=text, return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        out = model(**inp)
    res = proc.post_process_grounded_object_detection(
        out, inp.input_ids, threshold=box_threshold, text_threshold=text_threshold,
        target_sizes=[(h, w)],
    )[0]
    _, d = depth_map(jpeg_bytes, colorize=False)
    items = []
    for box, score, label in zip(res["boxes"], res["scores"], res["labels"]):
        x1, y1, x2, y2 = [float(v) for v in box]
        bx = int(max(0, min((x1 + x2) / 2, w - 1)))
        by = int(max(0, min(y2, h - 1)))
        items.append({
            "label": str(label), "score": round(float(score), 3),
            "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "dist_m": rough_distance_m(by, h),
            "rel_depth": round(float(d[by, bx]), 3),
        })
    items.sort(key=lambda x: -x["score"])
    return items


# ---------- F3 规则归纳（可选本地 LLM，懒加载） ----------
def tidy_rules(examples):
    """examples: [(object, place), ...]。ENABLE_LLM=1 时用本地 Qwen 归纳，否则用规则回退。"""
    if os.environ.get("ENABLE_LLM") == "1":
        try:
            return _llm_rules(examples)
        except Exception as e:
            return _fallback_rules(examples, note=f"LLM 不可用，已用规则回退（{e!r}）")
    return _fallback_rules(examples)


def _fallback_rules(examples, note=""):
    lines = "\n".join(f"- {o} → {p}" for o, p in examples)
    places = sorted({p for _, p in examples})
    text = (f"依据 {len(examples)} 条示例归纳的收纳规则：\n"
            f"把同类物品按示例放回对应位置；已知常用位置：{('、'.join(places))}。\n"
            f"示例明细：\n{lines}")
    if note:
        text += f"\n（{note}）"
    return {"rules": text, "model": "规则回退"}


def _llm_rules(examples):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    with _lock:
        if "qwen" not in _cache:
            tok = AutoTokenizer.from_pretrained(QWEN_DIR)
            model = AutoModelForCausalLM.from_pretrained(
                QWEN_DIR, torch_dtype=torch.float16, low_cpu_mem_usage=True).to(DEVICE).eval()
            _cache["qwen"] = (tok, model)
    tok, model = _cache["qwen"]
    prompt = ("你是家庭收纳助手。根据下面的示例，用一句中文总结这户人家的收纳规律，"
              "只输出一句总结。\n" + "\n".join(f"{o}放{p}" for o, p in examples) + "\n总结：")
    ids = tok(prompt, return_tensors="pt", truncation=True, max_length=512).to(DEVICE)
    with torch.no_grad():
        out = model.generate(**ids, max_new_tokens=60, do_sample=False,
                             pad_token_id=tok.eos_token_id)
    text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    return {"rules": text.split("\n")[0], "model": "Qwen2.5-3B-Instruct（本地）"}

#!/usr/bin/env python3
"""F1 消融：模型大小（S/B）× 输入分辨率（384/518/672）在 NYU-D 上的 AbsRel/δ1。

固定评测口径与主实验一致（Eigen 裁剪、尺度+偏移对齐、GT∈(0,10m)），默认取前 300 张
（与全量 654 张同分布子集，节省时间；--limit 0 跑全量）。

用法: ai312/bin/python scripts/abl_f1.py [--limit 300]
"""
import argparse
import json
import os

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import h5py
import numpy as np
import scipy.io as sio
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "NYUv2")
H, W = 480, 640
CROP_R, CROP_C = slice(45, 471), slice(41, 601)
BASE_DIR = os.path.join(HERE, "models", "depth-anything-v2-base")
CONFIGS = [
    ("ViT-S", "depth-anything/Depth-Anything-V2-Small-hf", 518),
    ("ViT-B", BASE_DIR, 518),
    ("ViT-S-384", "depth-anything/Depth-Anything-V2-Small-hf", 384),
    ("ViT-S-672", "depth-anything/Depth-Anything-V2-Small-hf", 672),
]


def align(pd, gt, sign=1):
    v = (gt > 0) & (gt < 10)
    A = np.stack([pd[v], np.ones(v.sum())], axis=1)
    coef, *_ = np.linalg.lstsq(A, 1.0 / gt[v], rcond=None)
    return 1.0 / np.clip(coef[0] * pd + coef[1], 1e-6, None)


def metrics(pd, gt):
    v = (gt > 0) & (gt < 10)
    p, g = pd[v], gt[v]
    return float(np.mean(np.abs(p - g) / g)), float(np.mean(np.maximum(p / g, g / p) < 1.25))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    idx = sio.loadmat(os.path.join(DATA, "splits.mat"))["testNdxs"].flatten().astype(int) - 1
    if args.limit:
        idx = idx[: args.limit]
    mat = h5py.File(os.path.join(DATA, "nyu_depth_v2_labeled.mat"), "r")

    results = []
    for name, mid, input_size in CONFIGS:
        try:
            proc = AutoImageProcessor.from_pretrained(mid)
            model = AutoModelForDepthEstimation.from_pretrained(mid).to("mps").eval()
        except Exception as e:
            print(f"[{name}] 模型加载失败（权重未就绪？）: {e!r}")
            continue
        ars, d1s = [], []
        for i in idx:
            img = mat["images"][i]
            img = np.transpose(img, (2, 1, 0)) if img.shape[0] == 3 else img
            gt = mat["depths"][i][:].T
            pil = Image.fromarray(np.ascontiguousarray(img)).resize((input_size, input_size), Image.BILINEAR)
            inp = proc(images=pil, return_tensors="pt").to("mps")
            with torch.no_grad():
                out = model(**inp)
            pred = torch.nn.functional.interpolate(
                out.predicted_depth[:, None].float(), (H, W), mode="bilinear", align_corners=True
            )[0, 0].cpu().numpy()
            ar, d1 = metrics(align(pred[CROP_R, CROP_C], gt[CROP_R, CROP_C], 1), gt[CROP_R, CROP_C])
            ars.append(ar); d1s.append(d1)
        r = {"config": name, "model": mid, "input_size": input_size, "n": len(idx),
             "abs_rel": round(float(np.mean(ars)), 4), "delta1": round(float(np.mean(d1s)), 4)}
        results.append(r)
        print(f"[{name}] AbsRel={r['abs_rel']}  d1={r['delta1']}  ({len(idx)} 张)", flush=True)
        del model

    out = {"feature": "F1-ablation", "paper_small": {"abs_rel": 0.053, "delta1": 0.973},
           "results": results}
    json.dump(out, open(os.path.join(HERE, "results", "abl_f1.json"), "w"),
              ensure_ascii=False, indent=2)
    print("已保存 results/abl_f1.json")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""F1 协议对比实验：在 NYU 测试集前 N 张上对比 4 种评测口径，确定官方口径。

用法: ai312/bin/python scripts/probe_protocol.py [--n 100]
"""
import argparse
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))

import h5py
import numpy as np
import scipy.io as sio
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "NYUv2")
MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
H, W, INPUT = 640, 480, 518
CROP_R, CROP_C = slice(41, 601), slice(45, 471)


def load_indices():
    s = sio.loadmat(os.path.join(DATA, "splits.mat"))
    return s["testNdxs"].flatten().astype(int) - 1


def metrics(pred, gt, mask):
    p, g = pred[mask], gt[mask]
    ok = np.isfinite(p) & (p > 0)
    p, g = p[ok], g[ok]
    abs_rel = float(np.mean(np.abs(p - g) / g))
    d1 = float(np.mean(np.maximum(p / g, g / p) < 1.25))
    return abs_rel, d1


def align_ss(pred_disp, gt, valid):
    A = np.stack([pred_disp[valid], np.ones(valid.sum())], axis=1)
    b = 1.0 / gt[valid]
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    return 1.0 / (coef[0] * pred_disp + coef[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    idx = load_indices()[: args.n]
    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to("mps").eval()
    mat = h5py.File(os.path.join(DATA, "nyu_depth_v2_labeled.mat"), "r")

    res = {k: [] for k in ["crop_ss", "crop_ss_clip", "crop_median", "full_ss"]}
    for i in idx:
        img = mat["images"][i]
        if img.shape[0] == 3:
            img = np.transpose(img, (1, 2, 0))
        gt = mat["depths"][i][:]
        pil = Image.fromarray(np.ascontiguousarray(img)).resize((INPUT, INPUT), Image.BILINEAR)
        inp = proc(images=pil, return_tensors="pt").to("mps")
        with torch.no_grad():
            out = model(**inp)
        pred = torch.nn.functional.interpolate(
            out.predicted_depth[:, None].float(), (H, W), mode="bilinear", align_corners=True
        )[0, 0].cpu().numpy()

        # 1) 裁剪 + 尺度偏移（不截断）
        g = gt[CROP_R, CROP_C]; p0 = pred[CROP_R, CROP_C]
        v = (g > 0) & (g < 10)
        res["crop_ss"].append(metrics(align_ss(p0, g, v), g, v))

        # 2) 裁剪 + 尺度偏移 + 深度截断到 [0.1, 10]
        pd = np.clip(align_ss(p0, g, v), 0.1, 10.0)
        res["crop_ss_clip"].append(metrics(pd, g, v))

        # 3) 裁剪 + 中位数缩放（深度空间，1/pred 后按中位数比缩放）
        p1 = 1.0 / np.clip(p0, 1e-6, None)
        scale = np.median(g[v]) / np.median(p1[v])
        res["crop_median"].append(metrics(p1 * scale, g, v))

        # 4) 全图 + 尺度偏移（之前的口径）
        vf = (gt > 0) & (gt < 10)
        res["full_ss"].append(metrics(align_ss(pred, gt, vf), gt, vf))

    print(f"在 {len(idx)} 张上对比（AbsRel / delta1）：")
    for k, v in res.items():
        arr = np.array(v)
        print(f"  {k:14s} AbsRel={arr[:,0].mean():.4f}  d1={arr[:,1].mean():.4f}")


if __name__ == "__main__":
    main()

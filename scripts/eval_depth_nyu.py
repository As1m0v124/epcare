#!/usr/bin/env python3
"""F1: Depth Anything V2-Small 在 NYU Depth V2 Eigen 测试集(654张)上的零样本相对深度评测。

对照论文: AbsRel 0.053 / delta1 0.973 (Depth Anything V2, ViT-S, NYU-D 测试集)。

评测口径（MiDaS 系列标准做法，论文 Table 2 同源）:
  1. 输入缩放到 518x518，模型输出相对深度（反深度/视差语义），双线性上采样回 480x640；
  2. 在与 GT 同网格上做尺度+偏移对齐（最小二乘，在反深度空间拟合）；
  3. 有效像素 = GT 深度 > 0（NYU 有效上限 10m）；
  4. AbsRel = mean(|pred-gt|/gt)，delta1 = mean(max(pred/gt, gt/pred) < 1.25)。
  深度方向约定在前 3 张图上自动校准并打印（不同实现约定不一）。

用法:
  ai312/bin/python scripts/eval_depth_nyu.py              # 全量 654 张
  ai312/bin/python scripts/eval_depth_nyu.py --limit 8    # 冒烟测试
"""
import argparse
import csv
import json
import os
import sys
import time

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
H, W = 480, 640  # 原始方向（mat 中以转置形式存储，读取时还原）
INPUT = 518
# Eigen 测试集标准裁剪（原始 480x640 方向）
CROP_R = slice(45, 471)
CROP_C = slice(41, 601)


def load_nyu_test_indices():
    splits = sio.loadmat(os.path.join(DATA, "splits.mat"))
    idx = splits["testNdxs"].flatten().astype(int) - 1  # MATLAB 1-based
    return idx, splits


def metrics(pred_depth, gt):
    valid = (gt > 0) & (gt < 10)
    if valid.sum() < 100:
        return None
    p, g = pred_depth[valid], gt[valid]
    abs_rel = float(np.mean(np.abs(p - g) / g))
    ratio = np.maximum(p / g, g / p)
    d1 = float(np.mean(ratio < 1.25))
    return abs_rel, d1


def align_scale_shift(pred_disparity, gt, sign):
    """在反深度空间最小二乘拟合 disp_pred' = a*disp_pred + b ≈ 1/gt，返回 pred_depth。"""
    valid = (gt > 0) & (gt < 10)
    disp = pred_disparity.copy()
    if sign < 0:  # 模型输出更像"深度"：先转成反深度
        disp = 1.0 / np.clip(disp, 1e-6, None)
    A = np.stack([disp[valid], np.ones(valid.sum())], axis=1)
    b = 1.0 / gt[valid]
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    aligned = coef[0] * disp + coef[1]
    aligned = np.clip(aligned, 1e-6, None)
    return 1.0 / aligned


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    args = ap.parse_args()

    idx, _ = load_nyu_test_indices()
    if args.limit:
        idx = idx[: args.limit]
    print(f"NYU 测试集: {len(idx)} 张, 设备: {args.device}")

    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to(args.device).eval()

    mat = h5py.File(os.path.join(DATA, "nyu_depth_v2_labeled.mat"), "r")
    images_ds, depths_ds = mat["images"], mat["depths"]

    def get_pair(i):
        img = images_ds[i]
        if img.shape[0] == 3:  # 存储为 (3, 640, 480) 的转置形式：还原成原始方向
            img = np.transpose(img, (2, 1, 0))  # -> (480, 640, 3)
        gt = depths_ds[i][:].T  # (640, 480) -> (480, 640)
        return np.ascontiguousarray(img), np.ascontiguousarray(gt)

    def predict(img_arr):
        pil = Image.fromarray(img_arr).resize((INPUT, INPUT), Image.BILINEAR)
        inputs = proc(images=pil, return_tensors="pt").to(args.device)
        with torch.no_grad():
            out = model(**inputs)
        pred = out.predicted_depth[0, None].float()
        pred = torch.nn.functional.interpolate(pred[None], (H, W), mode="bilinear", align_corners=True)
        return pred[0, 0].cpu().numpy()

    # 方向校准：前 min(3, n) 张较大误差的方向另有记；取 AbsRel 更低者
    calib = idx[: min(3, len(idx))]
    score = {1: 0.0, -1: 0.0}
    for i in calib:
        img, gt = get_pair(i)
        pred = predict(img)
        for sign in (1, -1):
            gc = gt[CROP_R, CROP_C]
            m = metrics(align_scale_shift(pred[CROP_R, CROP_C], gc, sign), gc)
            if m:
                score[sign] += m[0]
    sign = min(score, key=score.get)
    print(f"深度方向校准: sign={sign:+d} (AbsRel 累计 {score[1]:.3f} vs {score[-1]:.3f})")

    rows, abs_rels, d1s = [], [], []
    t0 = time.time()
    for k, i in enumerate(idx):
        img, gt = get_pair(i)
        pred = predict(img)
        gc = gt[CROP_R, CROP_C]
        m = metrics(align_scale_shift(pred[CROP_R, CROP_C], gc, sign), gc)
        if m is None:
            continue
        abs_rels.append(m[0]); d1s.append(m[1])
        rows.append([int(i), round(m[0], 4), round(m[1], 4)])
        if (k + 1) % 50 == 0:
            print(f"  {k+1}/{len(idx)}  AbsRel={np.mean(abs_rels):.4f}  d1={np.mean(d1s):.4f}  ({time.time()-t0:.0f}s)")

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    tag = f"_limit{args.limit}" if args.limit else ""  # 子集演示不覆盖全量结果
    csv_path = os.path.join(HERE, "results", f"nyu_f1{tag}.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["mat_index", "abs_rel", "delta1"]); w.writerows(rows)

    summary = {
        "feature": "F1",
        "model": MODEL_ID, "dataset": "NYU-D Eigen test", "n": len(abs_rels),
        "abs_rel": round(float(np.mean(abs_rels)), 4),
        "delta1": round(float(np.mean(d1s)), 4),
        "paper": {"abs_rel": 0.053, "delta1": 0.973},
        "depth_sign": sign, "device": args.device,
        "protocol": "MiDaS scale+shift alignment in disparity space; valid GT in (0,10m)",
        "elapsed_sec": round(time.time() - t0, 1),
        "limit": args.limit,
    }
    with open(os.path.join(HERE, "results", f"nyu_f1{tag}.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n===== F1 结果 =====")
    print(f"AbsRel = {summary['abs_rel']} (论文 0.053)")
    print(f"delta1 = {summary['delta1']} (论文 0.973)")
    print("明细:", csv_path)


if __name__ == "__main__":
    main()

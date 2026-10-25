#!/usr/bin/env python3
"""生成 F1 错例对比图：取 NYU-D 测试集里 AbsRel 最大的 10 张，
画 [原图 | GT 深度 | 预测深度（已对齐）]，输出 results/f1_errors.png。

用法: ai312/bin/python scripts/make_f1_error_sheet.py
"""
import csv
import json
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "NYUv2")
MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
H, W, INPUT = 480, 640, 518


def align(pred_disparity, gt, sign):
    valid = (gt > 0) & (gt < 10)
    disp = pred_disparity.copy()
    if sign < 0:
        disp = 1.0 / np.clip(disp, 1e-6, None)
    A = np.stack([disp[valid], np.ones(valid.sum())], axis=1)
    b = 1.0 / gt[valid]
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    return 1.0 / np.clip(coef[0] * disp + coef[1], 1e-6, None)


def main():
    rows = list(csv.DictReader(open(os.path.join(HERE, "results", "nyu_f1.csv"))))
    worst = sorted(rows, key=lambda r: float(r["abs_rel"]), reverse=True)[:10]
    sign = json.load(open(os.path.join(HERE, "results", "nyu_f1.json")))["depth_sign"]

    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to("mps").eval()
    mat = h5py.File(os.path.join(DATA, "nyu_depth_v2_labeled.mat"), "r")

    fig, axes = plt.subplots(10, 3, figsize=(11, 3.1 * 10))
    for row, ax in zip(worst, axes):
        i = int(row["mat_index"])
        img = mat["images"][i]
        if img.shape[0] == 3:  # (3,640,480) 转置存储 -> 还原原始方向 (480,640,3)
            img = np.transpose(img, (2, 1, 0))
        gt = mat["depths"][i][:].T  # (640,480) -> (480,640)
        pil = Image.fromarray(np.ascontiguousarray(img)).resize((INPUT, INPUT), Image.BILINEAR)
        inputs = proc(images=pil, return_tensors="pt").to("mps")
        with torch.no_grad():
            out = model(**inputs)
        pred = out.predicted_depth[:, None].float()
        pred = torch.nn.functional.interpolate(pred, (H, W), mode="bilinear", align_corners=True)[0, 0].cpu().numpy()
        pred_m = align(pred, gt, sign)
        ax[0].imshow(img)
        ax[0].set_title(f"#{i}  AbsRel={row['abs_rel']}", fontsize=9)
        ax[1].imshow(gt, cmap="plasma", vmin=0, vmax=10)
        ax[1].set_title("GT depth (m)", fontsize=9)
        ax[2].imshow(pred_m, cmap="plasma", vmin=0, vmax=10)
        ax[2].set_title("Pred depth (aligned)", fontsize=9)
        for a in ax:
            a.axis("off")
    fig.tight_layout()
    out_path = os.path.join(HERE, "results", "f1_errors.png")
    fig.savefig(out_path, dpi=110)
    print("已保存:", out_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""第 1 周交付物：10 张实验室照片的深度图 + 开放词汇检测结果 + CSV。

输入: results/selfcheck_photos/photo_*.jpg（EP 摄像头实拍）
输出:
  results/photos_demo/depth/depth_XX.png      深度图（inferno 配色，近亮远暗）
  results/photos_demo/detected/det_XX_<q>.jpg  检测框可视化
  results/photos_demo/photos_demo.csv         图片、中文描述、英文提示、框、置信度、相对深度

用法: ai312/bin/python scripts/week1_photos_demo.py
"""
import csv
import glob
import json
import os

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"   # 权重已在 HF 缓存中，离线加载避免网络重试
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import (
    AutoImageProcessor, AutoModelForDepthEstimation,
    AutoProcessor, AutoModelForZeroShotObjectDetection,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTOS = sorted(glob.glob(os.path.join(HERE, "results", "selfcheck_photos", "photo_*.jpg")))
OUT = os.path.join(HERE, "results", "photos_demo")
DEPTH_DIR = os.path.join(OUT, "depth")
DET_DIR = os.path.join(OUT, "detected")
GDINO_ID = "IDEA-Research/grounding-dino-tiny"

QUERIES = [  # 中文 -> 英文提示（文档要求：先翻成英文再送进模型）
    ("拖鞋", "slippers"),
    ("纸箱", "cardboard box"),
    ("椅子", "chair"),
    ("水瓶", "water bottle"),
    ("电线", "cable"),
]

# 粗估距离假设（阶段 2 用 200 张测距图标定后替换）：
# EP 相机 FOV 120°(对角，手册第 26 页) → 16:9 下水平 FOV≈113°，640 宽对应焦距 f≈212px；
# 相机高度假设 0.25m、俯仰 0（水平），地面为平面 → Z = f*h/(v - v_center)
F_PX = 212.0
CAM_H = 0.25


def rough_distance_m(box_bottom_row, img_h):
    dv = box_bottom_row - img_h / 2.0
    if dv <= 10:  # 接近地平线，估计不可靠
        return None
    return F_PX * CAM_H / dv


def main():
    os.makedirs(DEPTH_DIR, exist_ok=True)
    os.makedirs(DET_DIR, exist_ok=True)
    print(f"照片: {len(PHOTOS)} 张", flush=True)

    dproc = AutoImageProcessor.from_pretrained("depth-anything/Depth-Anything-V2-Small-hf")
    dmodel = AutoModelForDepthEstimation.from_pretrained("depth-anything/Depth-Anything-V2-Small-hf").to("mps").eval()

    gproc = AutoProcessor.from_pretrained(GDINO_ID)
    gmodel = AutoModelForZeroShotObjectDetection.from_pretrained(GDINO_ID).to("mps").eval()

    rows, n_det = [], 0
    for k, path in enumerate(PHOTOS):
        name = os.path.splitext(os.path.basename(path))[0]
        img = Image.open(path).convert("RGB")
        w, h = img.size

        # --- 深度图 ---
        dinp = dproc(images=img, return_tensors="pt").to("mps")
        with torch.no_grad():
            dout = dmodel(**dinp)
        depth = torch.nn.functional.interpolate(
            dout.predicted_depth[:, None].float(), (h, w), mode="bilinear", align_corners=True
        )[0, 0].cpu().numpy()
        norm = (depth - depth.min()) / (depth.max() - depth.min() + 1e-6)
        colored = cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        cv2.imwrite(os.path.join(DEPTH_DIR, f"depth_{k:02d}.png"), colored)
        print(f"  [{k+1}/{len(PHOTOS)}] 深度图完成", flush=True)

        # --- 5 句中文描述的开放词汇检测 ---
        canvas = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        for cn, en in QUERIES:
            inp = gproc(images=img, text=en + " .", return_tensors="pt").to("mps")
            with torch.no_grad():
                out = gmodel(**inp)
            res = gproc.post_process_grounded_object_detection(
                out, inp.input_ids, threshold=0.3, text_threshold=0.25,
                target_sizes=[(h, w)],
            )[0]
            for box, score, label in zip(res["boxes"], res["scores"], res["labels"]):
                x1, y1, x2, y2 = [int(v) for v in box]
                bx1, by1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
                bx2, by2 = max(0, min(x2, w - 1)), max(0, min(y2, h - 1))
                bottom = depth[min(by2, h - 1), (bx1 + bx2) // 2] if by2 < h else depth[-1, (bx1 + bx2) // 2]
                dist = rough_distance_m(by2, h)
                rows.append([os.path.basename(path), cn, en, f"{bx1},{by1},{bx2},{by2}",
                             round(float(score), 3), round(float(bottom), 3),
                             round(dist, 2) if dist else ""])
                n_det += 1
                cv2.rectangle(canvas, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                cv2.putText(canvas, f"{en} {score:.2f}", (bx1, max(14, by1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imwrite(os.path.join(DET_DIR, f"det_{k:02d}.jpg"), canvas)

    csv_path = os.path.join(OUT, "photos_demo.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        wri = csv.writer(f)
        wri.writerow(["图片", "中文描述", "英文提示", "框(x1,y1,x2,y2)", "置信度",
                      "框底部相对深度(DA-V2,越大越近)", "估计距离(粗估,m)"])
        wri.writerows(rows)

    summary = {
        "n_photos": len(PHOTOS), "queries": [q[0] for q in QUERIES],
        "n_detections": n_det,
        "note": "相对深度未换算米制；阶段 2 用 200 张测距图做尺度标定后输出真实距离",
        "csv": os.path.relpath(csv_path, HERE),
    }
    json.dump(summary, open(os.path.join(OUT, "photos_demo.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"完成: {n_det} 个检测 -> {csv_path}")


if __name__ == "__main__":
    main()

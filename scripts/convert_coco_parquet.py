#!/usr/bin/env python3
"""把 detection-datasets/coco 的 val parquet 转换成 COCO 标准格式（图片 + 标注 json）。

输出:
  data/coco/val2017/<file_name>.jpg
  results/coco_val_gt.json           （COCO 标注入，只含被转换的图片）

parquet 结构（detection-datasets/coco）: image_id, image{bytes,path}, width, height,
objects{bbox: [[x_min,y_min,x_max,y_max],...], category: [...], ...}（albumentations 约定，
绝对像素坐标）。转换时统一为 COCO 的 [x, y, w, h] 并重建 80 类 category id（COCO 官方 id）。

用法: ai312/bin/python scripts/convert_coco_parquet.py [--limit N]
"""
import argparse
import json
import os

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUETS = [
    os.path.join(HERE, "data", "coco", "val-00000.parquet"),
    os.path.join(HERE, "data", "coco", "val-00001.parquet"),
]
OUT_IMG = os.path.join(HERE, "data", "coco", "val2017")
OUT_GT = os.path.join(HERE, "results", "coco_val_gt.json")

COCO80_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]
# COCO 官方 category id（非连续）
COCO80_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
              24, 25, 27, 28, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47,
              48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 67, 70,
              72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87, 88, 89, 90]
NAME2ID = {n: i for n, i in zip(COCO80_NAMES, COCO80_IDS)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    os.makedirs(OUT_IMG, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_GT), exist_ok=True)

    images, annotations = [], []
    next_img_id, next_ann_id, count = 1, 1, 0
    for path in PARQUETS:
        if not os.path.exists(path) or count >= args.limit:
            continue
        t = pq.read_table(path, columns=["image", "width", "height", "objects"])
        data = t.to_pylist()
        for row in data:
            if count >= args.limit:
                break
            img_bytes = row["image"]["bytes"]
            file_name = f"{next_img_id:012d}.jpg"
            with open(os.path.join(OUT_IMG, file_name), "wb") as f:
                f.write(img_bytes)
            images.append({"id": next_img_id, "file_name": file_name,
                           "width": row["width"], "height": row["height"]})
            for bbox, cat in zip(row["objects"]["bbox"], row["objects"]["category"]):
                # parquet 的 category 是 0-79 的类别索引（COCO 原序），转成官方 category id
                name = COCO80_NAMES[int(cat)]
                cid = NAME2ID[name]
                if cid is None:
                    continue
                x1, y1, x2, y2 = bbox
                annotations.append({
                    "id": next_ann_id, "image_id": next_img_id, "category_id": cid,
                    "bbox": [float(x1), float(y1), float(max(0.0, x2 - x1)), float(max(0.0, y2 - y1))],
                    "area": float(max(0.0, x2 - x1) * max(0.0, y2 - y1)), "iscrowd": 0,
                })
                next_ann_id += 1
            next_img_id += 1
            count += 1
            if count % 100 == 0:
                print(f"  已转换 {count} 张")

    gt = {"images": images, "annotations": annotations,
          "categories": [{"id": i, "name": n} for n, i in zip(COCO80_NAMES, COCO80_IDS)]}
    json.dump(gt, open(OUT_GT, "w"))
    print(f"完成: {count} 张图片, {len(annotations)} 个标注 -> {OUT_GT}")


if __name__ == "__main__":
    main()

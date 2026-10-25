#!/usr/bin/env python3
"""F2: Grounding DINO (Swin-T) 在 COCO val2017 前 N 张上的零样本检测 AP。

对照论文: AP 48.4 (Grounding DINO T, O365+GoldG+Cap4M, 不在 COCO 上训练)。

实现说明:
  - 用 Hugging Face transformers 的 GroundingDinoForObjectDetection（官方仓库的
    自定义算子在本机不可编译；REPRO.md 已注明实现差异）；
  - 文字提示 = 80 个类别名小写，以 " . " 连接（Grounding DINO 标准用法）；
  - box_threshold=0.3, text_threshold=0.25（常用零样本设置，写进结果记录）；
  - AP 用 pycocotools 官方 bbox 评测，GT 只保留参与评测的图片。

用法:
  ai312/bin/python scripts/eval_gdino_coco500.py                # 前 500 张
  ai312/bin/python scripts/eval_gdino_coco500.py --limit 10     # 冒烟测试
"""
import argparse
import json
import os
import time

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))

import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COCO = os.path.join(HERE, "data", "coco")
MODEL_ID = "IDEA-Research/grounding-dino-tiny"

COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock",
    "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]


def norm(s):
    return s.strip().lower().replace("_", " ").replace(".", "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--box-thresh", type=float, default=0.3)
    ap.add_argument("--text-thresh", type=float, default=0.25)
    ap.add_argument("--ann", default="", help="标注 json（默认优先官方 annotations，否则用转换生成的）")
    ap.add_argument("--img-dir", default="", help="图片目录（默认 data/coco/val2017）")
    args = ap.parse_args()

    # 选标注来源：官方 instances_val2017.json 优先；没有则用 parquet 转换版
    if args.ann:
        ann_path = args.ann
    else:
        official = os.path.join(COCO, "annotations", "instances_val2017.json")
        converted = os.path.join(HERE, "results", "coco_val_gt.json")
        ann_path = official if os.path.exists(official) else converted
    img_dir = args.img_dir or os.path.join(COCO, "val2017")
    print("标注:", ann_path)
    ann = json.load(open(ann_path))
    images = sorted(ann["images"], key=lambda x: x["file_name"])[: args.limit]
    img_ids = {im["id"] for im in images}
    cat_by_name = {norm(c["name"]): c["id"] for c in ann["categories"]}
    gt = {
        "info": ann.get("info", {}),
        "licenses": ann.get("licenses", []),
        "images": images,
        "annotations": [a for a in ann["annotations"] if a["image_id"] in img_ids],
        "categories": ann["categories"],
    }
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    gt_path = os.path.join(HERE, "results", f"coco{args.limit}_gt.json")
    json.dump(gt, open(gt_path, "w"))
    print(f"评测图片: {len(images)} 张, GT 标注: {len(gt['annotations'])} 个")

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device).eval()
    text = " . ".join(COCO80).lower() + " ."

    dets = []
    t0 = time.time()
    for k, im in enumerate(images):
        path = os.path.join(img_dir, im["file_name"])
        img = Image.open(path).convert("RGB")
        inputs = proc(images=img, text=text, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        res = proc.post_process_grounded_object_detection(
            outputs, inputs.input_ids,
            box_threshold=args.box_thresh, text_threshold=args.text_thresh,
            target_sizes=[img.size[::-1]],
        )[0]
        for box, score, label in zip(res["boxes"], res["scores"], res["labels"]):
            cid = cat_by_name.get(norm(label))
            if cid is None:
                continue
            x1, y1, x2, y2 = [float(v) for v in box]
            dets.append({
                "image_id": im["id"], "category_id": cid,
                "bbox": [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)],
                "score": float(score),
            })
        if (k + 1) % 50 == 0:
            print(f"  {k+1}/{len(images)}  检出 {len(dets)} 框  ({time.time()-t0:.0f}s)")

    json.dump(dets, open(os.path.join(HERE, "results", f"coco{args.limit}_dets.json"), "w"))
    print(f"检测完成: {len(dets)} 框, 用时 {time.time()-t0:.0f}s，开始算 AP...")

    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    coco_gt = COCO(gt_path)
    if not dets:
        print("没有检测结果，无法评测")
        return
    coco_dt = coco_gt.loadRes(os.path.join(HERE, "results", f"coco{args.limit}_dets.json"))
    ev = COCOeval(coco_gt, coco_dt, "bbox")
    ev.evaluate(); ev.accumulate(); ev.summarize()
    stats = ev.stats
    summary = {
        "feature": "F2", "model": MODEL_ID, "dataset": f"COCO val2017 first {args.limit}",
        "n_images": len(images),
        "AP": round(float(stats[0]), 2), "AP50": round(float(stats[1]), 2),
        "paper_AP": 48.4,
        "impl": "HF transformers GroundingDINO (official CUDA ops unavailable on Mac)",
        "box_thresh": args.box_thresh, "text_thresh": args.text_thresh, "device": device,
        "n_detections": len(dets), "elapsed_sec": round(time.time() - t0, 1),
    }
    json.dump(summary, open(os.path.join(HERE, "results", "coco_f2.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"\n===== F2 结果 =====\nAP = {summary['AP']} (论文 48.4)  AP50 = {summary['AP50']}")


if __name__ == "__main__":
    main()

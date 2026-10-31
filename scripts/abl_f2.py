#!/usr/bin/env python3
"""F2 消融：提示词写法（3 种）× 框阈值（0.2–0.4）在 COCO val 前 N 张上的零样本 AP。

用法: ai312/bin/python scripts/abl_f2.py [--limit 100]
输出: results/abl_f2.json
"""
import argparse
import json
import os
import time

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COCO = os.path.join(HERE, "data", "coco")
GDINO_ID = "IDEA-Research/grounding-dino-tiny"

NAMES = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
         "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
         "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
         "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
         "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
         "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
         "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
         "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
         "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
         "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"]
IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
       24, 25, 27, 28, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47,
       48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 67, 70,
       72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87, 88, 89, 90]
NAME2ID = {n: i for n, i in zip(NAMES, IDS)}

STYLES = {
    "A_spaces": " . ".join(NAMES) + " .",
    "B_nospace": ". ".join(NAMES) + ".",
    "C_comma": ", ".join(NAMES) + " .",
}


def norm(s):
    return s.strip().lower().replace("_", " ").replace(".", "").strip()


def evaluate(gt, dets):
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    tmp = os.path.join(HERE, "results", "_abl_dets.json")
    json.dump(dets, open(tmp, "w"))
    if not dets:
        return 0.0, 0.0
    coco_gt = COCO(gt)
    dt = coco_gt.loadRes(tmp)
    ev = COCOeval(coco_gt, dt, "bbox")
    ev.evaluate(); ev.accumulate(); ev.summarize()
    return round(float(ev.stats[0]) * 100, 1), round(float(ev.stats[1]) * 100, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    ann = json.load(open(os.path.join(HERE, "results", "coco_val_gt.json")))
    images = sorted(ann["images"], key=lambda x: x["file_name"])[: args.limit]
    ids = {im["id"] for im in images}
    gt = {"images": images,
          "annotations": [a for a in ann["annotations"] if a["image_id"] in ids],
          "categories": ann["categories"]}
    gt_path = os.path.join(HERE, "results", "abl_f2_gt.json")
    json.dump(gt, open(gt_path, "w"))

    proc = AutoProcessor.from_pretrained(GDINO_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(GDINO_ID).to("mps").eval()

    results = []
    configs = [(s, 0.3, 0.25) for s in STYLES] + [("A_spaces", t, 0.25) for t in (0.2, 0.25, 0.35, 0.4)]
    seen = set()
    for style, bth, tth in configs:
        key = (style, bth, tth)
        if key in seen:
            continue
        seen.add(key)
        t0 = time.time()
        dets = []
        for im in images:
            img = Image.open(os.path.join(COCO, "val2017", im["file_name"])).convert("RGB")
            w, h = img.size
            inp = proc(images=img, text=STYLES[style], return_tensors="pt").to("mps")
            with torch.no_grad():
                out = model(**inp)
            res = proc.post_process_grounded_object_detection(
                out, inp.input_ids, threshold=bth, text_threshold=tth,
                target_sizes=[(h, w)])[0]
            for box, sc, label in zip(res["boxes"], res["scores"], res["labels"]):
                cid = NAME2ID.get(norm(str(label)))
                if cid is None:
                    continue
                x1, y1, x2, y2 = [float(v) for v in box]
                dets.append({"image_id": im["id"], "category_id": cid,
                             "bbox": [x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)],
                             "score": float(sc)})
        ap, ap50 = evaluate(gt_path, dets)
        r = {"style": style, "box_threshold": bth, "text_threshold": tth,
             "AP": ap, "AP50": ap50, "n_images": len(images),
             "elapsed_sec": round(time.time() - t0, 1)}
        results.append(r)
        print(f"[{style} box={bth}] AP={ap} AP50={ap50} ({r['elapsed_sec']}s)", flush=True)

    json.dump({"feature": "F2-ablation", "results": results},
              open(os.path.join(HERE, "results", "abl_f2.json"), "w"), ensure_ascii=False, indent=2)
    print("已保存 results/abl_f2.json")


if __name__ == "__main__":
    main()

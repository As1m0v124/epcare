#!/usr/bin/env python3
"""F2 补充评测：RefCOCO 指代表达定位 Top-1 准确率（IoU≥0.5）。

数据: lmms-lab-encoder/RefCOCO parquet（行 = 一个 GT 框 + answer 列表里的多条指代句）。
做法: 对每句指代文本，GDINO 取最高分框，与 GT 框 IoU≥0.5 记对。

用法:
  ai312/bin/python scripts/eval_refcoco.py                  # 每个 split 取前 1000 条指代
  ai312/bin/python scripts/eval_refcoco.py --max-refs 0     # 全量（很慢）
输出: results/refcoco.json（各 split 准确率 + 论文数字）
"""
import argparse
import glob
import io
import json
import os
import time

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import pyarrow.parquet as pq
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "RefCOCO")
GDINO_ID = "IDEA-Research/grounding-dino-tiny"
SPLITS = {"val": "val-*.parquet", "testA": "testA-*.parquet", "testB": "testB-*.parquet"}
PAPER = {"val": 50.41, "testA": 57.24, "testB": 43.21}
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def iou(a, b):
    """a,b: [x1,y1,x2,y2]"""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-refs", type=int, default=1000, help="每个 split 最多评测条数（0=全量）")
    ap.add_argument("--splits", default="val,testA,testB", help="逗号分隔的 split 列表")
    args = ap.parse_args()

    proc = AutoProcessor.from_pretrained(GDINO_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(GDINO_ID).to(DEVICE).eval()

    results = {}
    wanted = [s.strip() for s in args.splits.split(",") if s.strip()]
    for split, pattern in SPLITS.items():
        if split not in wanted:
            continue
        files = sorted(glob.glob(os.path.join(DATA, pattern)))
        if not files:
            print(f"[{split}] 数据未就绪，跳过", flush=True)
            continue
        correct, total = 0, 0
        t0 = time.time()
        for f in files:
            t = pq.read_table(f)
            for row in t.to_pylist():
                if args.max_refs and total >= args.max_refs:
                    break
                img = Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB")
                w, h = img.size
                gx, gy, gw, gh = row["bbox"]
                gt = (gx, gy, gx + gw, gy + gh)
                for ref in row["answer"]:
                    if args.max_refs and total >= args.max_refs:
                        break
                    inp = proc(images=img, text=ref.strip() + " .", return_tensors="pt").to(DEVICE)
                    with torch.no_grad():
                        out = model(**inp)
                    res = proc.post_process_grounded_object_detection(
                        out, inp.input_ids, threshold=0.3, text_threshold=0.25,
                        target_sizes=[(h, w)])[0]
                    if len(res["scores"]) == 0:
                        total += 1
                        continue
                    best = res["boxes"][int(torch.argmax(res["scores"]))]
                    pb = [float(v) for v in best]
                    correct += int(iou(pb, gt) >= 0.5)
                    total += 1
                if total % 100 == 0:
                    print(f"  [{split}] {total} 条  acc={correct/total:.3f}  ({time.time()-t0:.0f}s)", flush=True)
            if args.max_refs and total >= args.max_refs:
                break
        if total:
            results[split] = {"accuracy": round(100 * correct / total, 2),
                              "n_refs": total, "paper_accuracy": PAPER[split]}

    out_path = os.path.join(HERE, "results", "refcoco.json")
    merged = {}
    if os.path.exists(out_path):
        try:
            merged = json.load(open(out_path)).get("results", {})
        except Exception:
            merged = {}
    merged.update(results)
    out = {"feature": "F2", "dataset": "RefCOCO", "max_refs_per_split": args.max_refs,
           "results": merged, "device": DEVICE}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(out, open(out_path, "w"), ensure_ascii=False, indent=2)
    print("\n===== RefCOCO 结果 =====")
    for s, r in results.items():
        print(f"{s:6s} {r['accuracy']}%  ({r['n_refs']} 条, 论文 {r['paper_accuracy']}%)")


if __name__ == "__main__":
    main()

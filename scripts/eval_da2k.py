#!/usr/bin/env python3
"""F1 补充评测：DA-2K 相对深度基准（点对判断，对照论文 95.3%，ViT-S）。

标注格式: annotations.json = {image_path: [{point1:[h,w](近), point2:[h,w], closer_point:"point1"}]}
模型输出为反深度（越大越近），逐对比较 depth[p1] > depth[p2]。

用法: ai312/bin/python scripts/eval_da2k.py [--limit N]
输出: results/da2k.json（总准确率 + 分场景准确率）
"""
import argparse
import json
import os
import time

os.environ.setdefault("HF_HOME", os.path.expanduser("~/ep-project/cache/hf"))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data", "DA-2K", "DA-2K")
MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
INPUT = 518


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ann = json.load(open(os.path.join(DATA, "annotations.json")))
    keys = sorted(ann)[: args.limit or None]
    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL_ID).to("mps").eval()

    per_scene, all_correct, all_total = {}, 0, 0
    t0 = time.time()
    for k, path in enumerate(keys):
        img = Image.open(os.path.join(DATA, path)).convert("RGB")
        w, h = img.size
        inp = proc(images=img.resize((INPUT, INPUT), Image.BILINEAR), return_tensors="pt").to("mps")
        with torch.no_grad():
            out = model(**inp)
        d = torch.nn.functional.interpolate(
            out.predicted_depth[:, None].float(), (h, w), mode="bilinear", align_corners=True
        )[0, 0].cpu().numpy()
        scene = path.split("/")[1]
        sc, st = per_scene.get(scene, (0, 0))
        for a in ann[path]:
            p1, p2 = a["point1"], a["point2"]
            closer = p1 if a.get("closer_point", "point1") == "point1" else p2
            other = p2 if closer is p1 else p1
            ok = float(d[closer[0], closer[1]]) > float(d[other[0], other[1]])
            all_correct += int(ok); all_total += 1
            sc, st = sc + int(ok), st + 1
        per_scene[scene] = (sc, st)
        if (k + 1) % 100 == 0:
            print(f"  {k+1}/{len(keys)}  累计准确率 {all_correct/all_total:.3f}  ({time.time()-t0:.0f}s)", flush=True)

    summary = {
        "feature": "F1", "model": MODEL_ID, "dataset": "DA-2K",
        "accuracy": round(100 * all_correct / all_total, 2),
        "paper_accuracy": 95.3,
        "n_images": len(keys), "n_pairs": all_total,
        "per_scene": {s: round(100 * c / t, 2) for s, (c, t) in sorted(per_scene.items())},
        "device": "mps", "elapsed_sec": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "da2k.json"), "w"),
              ensure_ascii=False, indent=2)
    print("\n===== DA-2K 结果 =====")
    print(f"准确率 {summary['accuracy']}% (论文 95.3%)，{summary['n_pairs']} 对")
    for s, v in summary["per_scene"].items():
        print(f"  {s:22s} {v}%")


if __name__ == "__main__":
    main()

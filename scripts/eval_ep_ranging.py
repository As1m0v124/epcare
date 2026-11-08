#!/usr/bin/env python3
"""EP 居家测距集评测：三种测距做法对比（阶段 2 · F1）。

输入 data/ep_ranging/measurements.csv（需带 u_px/v_px 地面接触点，采集脚本点选）
输出 results/ep_ranging_eval.json + 终端表格。

三种做法：
  A. 固定针孔：Z = f*H/(v - h/2)，沿用当前系统假设（F=212px@640w, H=0.25m, 俯角 0）
  B. 地平面标定：Z = a/(v - y_h)，用训练图拟合 a、y_h（等价于标定相机高度/俯仰）
  C. 深度标定：1/Z = a*disparity + b，用 Depth Anything V2 的相对深度拟合尺度/偏移

按图片切分训练/测试（默认每 3 张取 1 张测试），避免同图泄漏。
样本 <6 张时只报告 A，并明确标注“样本不足，不作结论”。

用法:
  ai312/bin/python scripts/eval_ep_ranging.py                 # MPS（先停掉后端/控制服务更稳）
  ai312/bin/python scripts/eval_ep_ranging.py --cpu           # 与在线服务并行时用 CPU
"""
import argparse
import csv
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

F_PX_640 = 212.0
CAM_H = 0.25


def metrics(rows):
    if not rows:
        return {"n": 0}
    err = [abs(p["z"] - p["gt"]) / p["gt"] for p in rows]
    rmse = math.sqrt(sum((p["z"] - p["gt"]) ** 2 for p in rows) / len(rows))
    d1 = sum(1 for p in rows if max(p["z"] / p["gt"], p["gt"] / p["z"]) < 1.25) / len(rows)
    return {"n": len(rows), "absrel": round(float(np.mean(err)), 4),
            "rmse_m": round(float(rmse), 4), "delta1": round(float(d1), 4)}


def fit_row_model(train):
    """Z = a/(v - y_h)：网格搜 y_h，闭式解 a。"""
    h = train[0]["h"]
    best = None
    # 相机下俯时地平线行可能在画面外（甚至为负），搜索范围放宽
    for yh in np.arange(-3.0 * h, 2.0 * h, 1.0):
        if any(abs(p["v"] - yh) < 1e-6 for p in train):
            continue  # 该 y_h 会让某个点除零
        r = np.array([1.0 / (p["v"] - yh) for p in train])
        z = np.array([p["gt"] for p in train])
        denom = float((r * r).sum())
        if denom <= 0:
            continue
        a = float((z * r).sum() / denom)
        if a <= 0:
            continue
        pred = a * r
        rmse = float(np.sqrt(np.mean((pred - z) ** 2)))
        if best is None or rmse < best[0]:
            best = (rmse, a, float(yh))
    return {"a": best[1], "y_h": best[2]} if best else None


def fit_depth_model(train):
    """1/Z = a*disparity + b（最小二乘）。"""
    d = np.array([p["disp"] for p in train])
    invz = np.array([1.0 / p["gt"] for p in train])
    A = np.stack([d, np.ones_like(d)], axis=1)
    try:
        (a, b), *_ = np.linalg.lstsq(A, invz, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return {"a": float(a), "b": float(b)} if a > 0 else None


def predict_row(m, v):
    den = v - m["y_h"]
    return m["a"] / den if den > 1e-6 else None


def predict_depth(m, disp):
    inv = m["a"] * disp + m["b"]
    return 1.0 / inv if inv > 1e-4 else None


def load_points(csv_path, data_dir):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    pts, missing = [], 0
    for r in rows:
        try:
            u, v = float(r["u_px"]), float(r["v_px"])
            gt = float(r["distance_m"])
        except (KeyError, TypeError, ValueError):
            missing += 1
            continue
        if gt <= 0.05 or u < 0 or v < 0:
            missing += 1
            continue
        img = os.path.join(data_dir, "images", r["file"])
        if not os.path.exists(img):
            missing += 1
            continue
        pts.append({"file": r["file"], "img": img, "object": r.get("object", ""),
                    "surface": r.get("surface", ""), "light": r.get("light", ""),
                    "u": int(round(u)), "v": int(round(v)), "gt": gt})
    return pts, len(rows), missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "data", "ep_ranging", "measurements.csv"))
    ap.add_argument("--data", default=os.path.join(HERE, "data", "ep_ranging"))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "ep_ranging_eval.json"))
    ap.add_argument("--test-every", type=int, default=3, help="每 N 张取 1 张做测试")
    ap.add_argument("--cpu", action="store_true", help="用 CPU 推理，避免与在线服务抢 MPS")
    args = ap.parse_args()

    pts, n_rows, missing = load_points(args.csv, args.data)
    print(f"CSV {n_rows} 条，可评测 {len(pts)} 条（缺图/缺点击标注 {missing} 条）")
    if not pts:
        print("没有可评测的点：先用 collect_ranging_data.py 在图上点物体与地面接触点。")
        return

    if args.cpu:
        import backend.ml as ml
        ml.DEVICE = "cpu"
    from backend import ml

    # 每张图只推理一次
    by_file = {}
    for p in pts:
        by_file.setdefault(p["file"], []).append(p)
    files = sorted(by_file)
    for fn in files:
        raw = open(by_file[fn][0]["img"], "rb").read()
        _, dmap = ml.depth_map(raw, colorize=False)
        h, w = dmap.shape[:2]
        for p in by_file[fn]:
            u = min(max(p["u"], 0), w - 1)
            v = min(max(p["v"], 0), h - 1)
            p["u"], p["v"], p["h"] = u, v, h
            p["disp"] = float(dmap[v, u])
            f = F_PX_640 * (h / 360.0)
            dv = v - h / 2.0
            p["z_fixed"] = f * CAM_H / dv if dv > 10 else None

    # 按真实距离分层切分：每个距离组各留约 1/test_every 张测试，保证测试覆盖近/中/远
    from collections import defaultdict
    groups = defaultdict(list)
    for p in pts:
        groups[(p.get("surface", ""), round(p["gt"], 1))].append(p["file"])
    test_files = set()
    for key, fs in groups.items():
        if len(fs) >= 2:
            test_files.update(set(fs[:: args.test_every]))
    if not test_files and len(files) >= 6:
        test_files = set(files[:: args.test_every])
    test_files = {f for f in test_files if f in files}
    train = [p for p in pts if p["file"] not in test_files]
    test = [p for p in pts if p["file"] in test_files]
    calib = {"n_files": len(files), "n_points": len(pts), "test_files": len(test_files)}

    print("\n=== A. 固定针孔（系统当前假设）===")
    a_rows = [{"gt": p["gt"], "z": p["z_fixed"]} for p in pts if p["z_fixed"] is not None]
    a_test = [{"gt": p["gt"], "z": p["z_fixed"]} for p in test if p["z_fixed"] is not None]
    if len(a_rows) < len(pts) * 0.5:
        print(f"⚠️ 只有 {len(a_rows)}/{len(pts)} 个点在画面中线以下；相机俯角明显不为 0，A 的假设不成立。")
    res_a = metrics(a_test if test_files else a_rows)
    print(res_a)

    results = {"dataset": "EP ranging", "n_files": len(files), "n_points": len(pts),
               "split": {"train_points": len(train), "test_points": len(test), "test_every": args.test_every},
               "A_fixed_pinhole": res_a, "calibration": calib}

    if len(train) >= 5 and len(test) > 0:
        row_m = fit_row_model(train)
        depth_m = fit_depth_model(train)
        calib["row_model"] = row_m
        calib["depth_model"] = depth_m

        b_test, c_test = [], []
        for p in test:
            if row_m:
                z = predict_row(row_m, p["v"])
                if z:
                    b_test.append({"gt": p["gt"], "z": z})
            if depth_m:
                z = predict_depth(depth_m, p["disp"])
                if z:
                    c_test.append({"gt": p["gt"], "z": z})
        res_b = metrics(b_test)
        res_c = metrics(c_test)
        print("\n=== B. 地平面标定（row→distance）===")
        print(row_m, res_b)
        print("  B 的测试点残差（>20% 重点检查距离标注/接触点）：")
        for p in test:
            z = predict_row(row_m, p["v"]) if row_m else None
            if z:
                print(f"    {p['file']} {p['object']}: gt={p['gt']:.2f}m v={p['v']} pred={z:.2f}m "
                      f"err={abs(z-p['gt'])/p['gt']*100:.0f}%")
        print("\n=== C. 深度标定（1/Z = a*disp + b）===")
        print(depth_m, res_c)
        results["B_ground_calibrated"] = {**res_b, "params": row_m}
        results["C_depth_calibrated"] = {**res_c, "params": depth_m}
        for name, res in (("A_fixed_pinhole", res_a), ("B_ground_calibrated", res_b),
                          ("C_depth_calibrated", res_c)):
            print(f"  {name:22s} AbsRel {res.get('absrel')}  RMSE {res.get('rmse_m')}  δ1 {res.get('delta1')}")
    else:
        print("\n样本不足（训练点 <5 或测试点 0）：只报告 A；采集 ≥20 张后再拟合 B/C。")
        results["note"] = "样本不足，B/C 未拟合；当前数字仅作管线自检，不作结论"

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=2)

    # 同时输出可直接贴进周报的 Markdown 表
    md = [f"# EP 居家测距集评测（{time.strftime('%Y-%m-%d')}）", "",
          f"- 图片 {results['n_files']} 张 / 标注点 {results['n_points']} 条",
          f"- 切分：训练 {results['split']['train_points']} 点，测试 {results['split']['test_points']} 点（每 {args.test_every} 张取 1 张测试）", ""]
    rows_md = [("A 固定针孔（现有假设）", results["A_fixed_pinhole"])]
    if "B_ground_calibrated" in results:
        rows_md.append(("B 地平面标定", results["B_ground_calibrated"]))
    if "C_depth_calibrated" in results:
        rows_md.append(("C 深度标定", results["C_depth_calibrated"]))
    md += ["| 方法 | 测试点 | AbsRel | RMSE(m) | δ1 |", "|---|---|---|---|---|"]
    for name, r in rows_md:
        md.append(f"| {name} | {r.get('n', 0)} | {r.get('absrel', '-')} | {r.get('rmse_m', '-')} | {r.get('delta1', '-')} |")
    if results.get("note"):
        md += ["", f"> {results['note']}"]
    md_path = os.path.splitext(args.out)[0] + ".md"
    open(md_path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"\n已保存 {args.out} 和 {md_path}")


if __name__ == "__main__":
    main()

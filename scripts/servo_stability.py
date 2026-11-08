#!/usr/bin/env python3
"""舵机连续步进稳定性测试：20 次 ±10mm，逐步回读位置，统计到位误差。

用法: ai312/bin/python scripts/servo_stability.py --n 20
真机 real 模式；机械臂在安全行程内（当前 x/y 各留 ±30mm 余量）。
"""
import argparse
import json
import os
import statistics
import time

import requests

B = "http://127.0.0.1:8001"


def pos():
    st = requests.get(B + "/state", timeout=5).json()
    return st.get("arm_pos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--axis", choices=["x", "y"], default="x")
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--settle", type=float, default=0.8, help="动作完成后等待回读稳定的秒数")
    args = ap.parse_args()

    p0 = pos()
    print("起始位置:", p0)
    if not p0:
        raise SystemExit("读不到机械臂位置，先确认已连接 real")

    rows, prev = [], p0
    for i in range(args.n):
        d = args.step if i % 2 == 0 else -args.step
        body = {"x_mm": d, "y_mm": 0} if args.axis == "x" else {"x_mm": 0, "y_mm": d}
        t0 = time.time()
        r = requests.post(B + "/arm", json=body, timeout=10)
        sec = round(time.time() - t0, 3)
        time.sleep(args.settle)
        cur = pos()
        idx = 0 if args.axis == "x" else 1
        moved = (cur[idx] - prev[idx]) if cur else None
        rows.append({"i": i + 1, "cmd": d, "status": r.status_code, "sec": sec,
                     "pos": cur, "delta_mm": moved,
                     "err_mm": abs(abs(moved) - args.step) if moved is not None else None})
        prev = cur or prev
        print(f"  {i+1:02d}: cmd={d:+d}mm  {r.status_code}  {sec:.2f}s  pos={cur}  Δ={moved}mm")

    errs = [r["err_mm"] for r in rows if r["err_mm"] is not None]
    p_end = pos()
    drift = (p_end[0] - p0[0]) if p_end else None
    ok = sum(1 for r in rows if r["status"] == 200)
    summary = {
        "n": args.n, "axis": args.axis, "step_mm": args.step,
        "start": p0, "end": p_end, "drift_mm": drift, "http_200": ok,
        "mean_err_mm": round(statistics.mean(errs), 2) if errs else None,
        "max_err_mm": max(errs) if errs else None,
        "within_3mm": sum(1 for e in errs if e <= 3),
        "rows": rows,
        "direction_ok": all((r["delta_mm"] or 0) * r["cmd"] > 0 for r in rows),
        "verdict": ("✅ 连续步进稳定：全部执行、方向正确" if ok == args.n
                    and all((r["delta_mm"] or 0) * r["cmd"] > 0 for r in rows)
                    else "⚠️ 存在未执行/方向异常步骤，见 rows"),
    }
    os.makedirs("results", exist_ok=True)
    json.dump(summary, open("results/servo_stability.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

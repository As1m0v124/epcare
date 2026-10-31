#!/usr/bin/env python3
"""EP 居家测距数据集采集助手（阶段 2，接真机后使用）。

流程：机器人放在地面，用卷尺把物体摆到已知距离 → 回车拍照 → 输入距离/标签 → 自动记 CSV。
数据用于 F1 的「框底边估距 vs 深度+地平面 vs 深度+标定点」三种做法对比与尺度标定。

用法（先 bash start.sh real，或 start.sh replay 练习流程）:
  ai312/bin/python scripts/collect_ranging_data.py --out data/ep_ranging --n 200
"""
import argparse
import csv
import os
import time

import requests

API = os.environ.get("EPCARE_API", "http://127.0.0.1:8000")
USER = os.environ.get("EPCARE_USER", "admin")
PWD = os.environ.get("EPCARE_PASS", "admin123")
SURFACES = ["瓷砖", "木地板", "地毯"]
LIGHTS = ["白天", "夜间开灯"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ep_ranging")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    os.makedirs(os.path.join(args.out, "images"), exist_ok=True)
    csv_path = os.path.join(args.out, "measurements.csv")
    new = not os.path.exists(csv_path)

    s = requests.Session()
    s.post(API + "/api/login", json={"username": USER, "password": PWD}, timeout=10).raise_for_status()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["file", "object", "distance_m", "surface", "light", "ts"])
        print(f"目标 {args.n} 张。把物体摆到已知距离，回车拍照；输入 q 退出。")
        print(f"地面类型：{SURFACES}；光照：{LIGHTS}")
        k = 0
        while k < args.n:
            cmd = input(f"\n[{k+1}/{args.n}] 回车拍照（或 q 退出）: ").strip()
            if cmd.lower() == "q":
                break
            try:
                r = s.get(API + "/api/depth.jpg", timeout=30)  # 触发确认服务在线
                frame = s.get(API + "/api/control/frame.jpg", timeout=10).content
            except Exception as e:
                print("拍不到画面（控制服务未连接？）:", e)
                continue
            fn = f"{int(time.time())}_{k:03d}.jpg"
            open(os.path.join(args.out, "images", fn), "wb").write(frame)
            spec = input("  物体与距离（如 水瓶:0.5,盒子:0.5,收纳包:0.5）: ").strip()
            pairs = []
            for part in spec.replace("，", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" in part:
                    o, d = part.split(":", 1)
                elif "=" in part:
                    o, d = part.split("=", 1)
                else:
                    o, d = part, "0"
                pairs.append((o.strip(), d.strip()))
            if not pairs:
                o = input("  物体名称: ").strip() or "object"
                d = input("  距离（米）: ").strip() or "0"
                pairs = [(o, d)]
            surf = input(f"  地面 {SURFACES[0]}/{SURFACES[1]}/{SURFACES[2]}: ").strip() or SURFACES[0]
            light = input(f"  光照 {LIGHTS[0]}/{LIGHTS[1]}: ").strip() or LIGHTS[0]
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            for o, d in pairs:
                w.writerow([fn, o, d, surf, light, ts])
            f.flush()
            k += 1
    print(f"已保存 {k} 条 → {csv_path}")


if __name__ == "__main__":
    main()

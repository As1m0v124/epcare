#!/usr/bin/env python3
"""真机巡检一圈（方形路线）演示/录屏用：4×(前进 side + 右转 90°)，每角拍照。

用法: ai312/bin/python scripts/patrol_loop_demo.py --side 0.3 --confirm
要求：机器人在空旷处（建议 1.5m×1.5m），电量 >30%，已连接 real 模式。
"""
import argparse
import json
import requests

B = "http://127.0.0.1:8000"
s = requests.Session()
s.post(B + "/api/login", json={"username": "admin", "password": "admin123"}).raise_for_status()

ap = argparse.ArgumentParser()
ap.add_argument("--side", type=float, default=0.3)
ap.add_argument("--confirm", action="store_true", help="现场已确认周围 1.5m 无障碍")
args = ap.parse_args()
if not args.confirm:
    raise SystemExit("请先确认场地安全，再加 --confirm 运行")

r = s.post(B + "/api/tasks/patrol_loop",
           json={"side_m": args.side, "confirm_real": True}, timeout=180)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=1))

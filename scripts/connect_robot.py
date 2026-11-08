#!/usr/bin/env python3
"""等待机器人上线并自动连接控制服务（开机后使用）。

用法:
  ai312/bin/python scripts/connect_robot.py --ip 10.197.63.238 --timeout 120
"""
import argparse
import os
import time

import requests

BASE = os.environ.get("EPCARE_CONTROL", "http://127.0.0.1:8001")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=os.environ.get("EP_IP", "10.197.63.238"))
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--mode", default="real")
    args = ap.parse_args()

    os.environ["EP_IP"] = args.ip  # 控制服务已启动，仅用于日志
    deadline = time.time() + args.timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            st = requests.get(BASE + "/state", timeout=3).json()
            if st.get("connected"):
                print(f"✅ 已连接机器人（mode={st.get('mode')}, 电量={st.get('battery')}%, "
                      f"queue={st.get('queue')}）")
                return 0
        except Exception:
            pass
        try:
            print(f"[{attempt}] 尝试连接 {args.ip} ...", flush=True)
            r = requests.post(BASE + "/connect", json={"mode": args.mode}, timeout=45)
            print("  /connect:", r.status_code, r.text[:120])
            if r.ok:
                time.sleep(2)
                st = requests.get(BASE + "/state", timeout=3).json()
                if st.get("connected"):
                    print(f"✅ 已连接机器人（mode={st.get('mode')}, 电量={st.get('battery')}%, "
                          f"queue={st.get('queue')}）")
                    return 0
        except Exception as e:
            print("  连接失败:", type(e).__name__)
        time.sleep(3)
    print(f"❌ {args.timeout:.0f}s 内未连上机器人：确认机器人已开机、与 Mac 同一 Wi-Fi，"
          f"或检查 EP_IP（当前 {args.ip}）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""稳定复现「指令堆积卡死」并验证修复。

场景（与网页上连续点机械臂一致）：并发发 N 条 10mm 步进，每条都要等动作完成。
  - 旧版（EPCARE_LEGACY=1，直接并发调 SDK，无队列）：请求在服务里无限堆积，
    动作一条条排队执行；之后单条正常指令要等几十秒甚至超时 → 卡死；
  - 新版（有界队列，1 执行 + 1 排队）：多余请求立即 429，状态接口始终可查，
    后续单条指令迅速得到响应 → 不再卡死。

用法（控制服务已连接真机 real）:
  ai312/bin/python scripts/repro_pileup.py --n 20 --tag before   # 对 legacy 服务
  ai312/bin/python scripts/repro_pileup.py --n 20 --tag after    # 对默认服务
"""
import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "http://127.0.0.1:8001"


def burst(i):
    t0 = time.time()
    sign = 10 if i % 2 == 0 else -10  # 正负交替，净位移≈0
    try:
        r = requests.post(BASE + "/arm", json={"x_mm": sign, "y_mm": 0}, timeout=20)
        return {"i": i, "status": r.status_code, "sec": round(time.time() - t0, 3)}
    except Exception as e:
        return {"i": i, "status": "timeout", "sec": round(time.time() - t0, 3), "err": type(e).__name__}


def state_latency():
    t0 = time.time()
    try:
        r = requests.get(BASE + "/state", timeout=5)
        return {"status": r.status_code, "sec": round(time.time() - t0, 3)}
    except Exception as e:
        return {"status": "timeout", "sec": round(time.time() - t0, 3), "err": type(e).__name__}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()

    print(f"阶段 1：并发发送 {args.n} 条机械臂步进（每条等完成，正负交替）...")
    pool = ThreadPoolExecutor(args.n)
    futs = [pool.submit(burst, i) for i in range(args.n)]
    time.sleep(2.0)  # 等堆积形成，此时请求还在服务里排队

    print("阶段 2：堆积进行中，状态接口是否还能及时响应...")
    st = state_latency()
    print("  /state:", st)

    print("阶段 3：堆积进行中，再发 1 条正常指令，测量要等多久...")
    t0 = time.time()
    try:
        r = requests.post(BASE + "/arm", json={"x_mm": -10, "y_mm": 0}, timeout=10)
        probe = {"status": r.status_code, "sec": round(time.time() - t0, 3)}
    except Exception as e:
        probe = {"status": "timeout", "sec": round(time.time() - t0, 3), "err": type(e).__name__}
    print("  探测指令:", probe)

    burst_res = [f.result() for f in futs]
    pool.shutdown()
    counts = {}
    for r in burst_res:
        counts[str(r["status"])] = counts.get(str(r["status"]), 0) + 1
    secs = sorted(r["sec"] for r in burst_res)
    print("  批量结果:", counts, " 延迟 p50/max:", secs[len(secs)//2], max(secs))

    frozen = (probe["status"] == "timeout" or probe["sec"] >= 5
              or st["status"] == "timeout" or st["sec"] >= 3)
    summary = {
        "tag": args.tag, "burst_n": args.n, "burst_status": counts,
        "burst_latency_p50": secs[len(secs)//2], "burst_latency_max": max(secs),
        "state": st, "probe": probe, "frozen": frozen,
        "verdict": "❌ 卡死已复现：堆积后指令/状态长时间无响应" if frozen
                   else "✅ 未卡死：堆积被限流，状态与指令仍及时响应",
    }
    os.makedirs("results", exist_ok=True)
    json.dump(summary, open(f"results/pileup_{args.tag}.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""稳定复现「指令堆积卡死」并验证修复。

场景（与网页上连续操作一致）：并发发 N 条动作，每条都等完成；再发第 N+1 条探测指令。
  - 旧版（EPCARE_LEGACY=1，直接并发调 SDK，无队列）：请求无限堆积，探测指令十几秒/超时 → 卡死；
  - 新版（有界队列，1 执行 + 1 排队）：多余请求立即 429，探测指令迅速响应 → 不卡死。

用法（控制服务已连接真机 real）:
  ai312/bin/python scripts/repro_pileup.py --n 36 --tag before --annotate
  ai312/bin/python scripts/repro_pileup.py --n 36 --tag after
  ai312/bin/python scripts/repro_pileup.py --n 36 --act move   # 演示移动小车（原地转）
"""
import argparse
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "http://127.0.0.1:8001"


def payload(i, act):
    sign = 10 if i % 2 == 0 else -10
    if act == "move":
        return {"x": 0, "y": 0, "z": sign}  # 原地转 ±10°，画面变化明显且不位移
    return {"x_mm": sign, "y_mm": 0}


def burst(i, act):
    t0 = time.time()
    try:
        r = requests.post(BASE + ("/move" if act == "move" else "/arm"),
                          json=payload(i, act), timeout=20)
        return {"i": i, "status": r.status_code, "sec": round(time.time() - t0, 3)}
    except Exception as e:
        return {"i": i, "status": "timeout", "sec": round(time.time() - t0, 3), "err": type(e).__name__}


def grab():
    try:
        r = requests.get(BASE + "/frame.jpg", timeout=5)
        return r.content if r.status_code == 200 and len(r.content) > 10000 else None
    except Exception:
        return None


def frame_diff(a, b):
    if not a or not b:
        return None
    import cv2
    import numpy as np
    ia = cv2.imdecode(np.frombuffer(a, np.uint8), cv2.IMREAD_COLOR)
    ib = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    if ia is None or ib is None or ia.shape != ib.shape:
        return None
    return round(float(np.mean(cv2.absdiff(ia, ib))) / 255 * 100, 2)


def annotate(after_bytes, summary, tag):
    """在最后一帧上标注判定，生成视频里可展示的证据图（中文用 PingFang）。"""
    if not after_bytes:
        return None
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    img = cv2.imdecode(np.frombuffer(after_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.resize(img, (img.shape[1] * 2, img.shape[0] * 2))
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil, "RGBA")
    draw.rectangle([0, 0, pil.width, 190], fill=(0, 0, 0, 170))

    def _font(size):
        # macOS 自带中文字体（PingFang.ttc 在部分系统上 PIL 打不开）
        for path, idx in [("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
                          ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
                          ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0)]:
            try:
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                continue
        return ImageFont.load_default()

    f_big, f_mid = _font(46), _font(30)

    frozen = summary["frozen"]
    color = (255, 80, 80) if frozen else (80, 255, 120)
    title = "旧版演示：指令堆积卡死" if frozen else "修复版：控制正常"
    draw.text((20, 12), title, font=f_big, fill=color)
    act_cn = "移动小车（原地转）" if summary.get("act") == "move" else "机械臂步进"
    lines = [
        f"动作：{act_cn}，批量 {summary['burst_n']} 条：{summary['burst_status']}",
        f"第 {summary['burst_n']+1} 条探测：{summary['probe']['status']} / {summary['probe']['sec']}s",
        (f"画面变化：{summary.get('frame_diff_pct', '?')}%"
         f"（{'无变化' if summary.get('frame_static') else '有变化'}）"),
        ("判定：卡死（画面无变化 + 新指令超时）" if frozen and summary.get("frame_static")
         else "判定：卡死（新指令无响应）" if frozen else "判定：正常（指令及时响应）"),
    ]
    for k, line in enumerate(lines):
        draw.text((24, 76 + k * 28), line, font=f_mid, fill=(255, 255, 255))

    out = os.path.join("results", f"pileup_{tag}_annotated.jpg")
    os.makedirs("results", exist_ok=True)
    pil.save(out, quality=92)
    print("标注图:", out)
    if sys_platform() == "darwin":
        try:
            subprocess.Popen(["open", out])
        except Exception:
            pass
    return out


def sys_platform():
    import sys
    return sys.platform


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=36)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--act", choices=["arm", "move"], default="arm")
    ap.add_argument("--annotate", action="store_true", help="生成带判定的标注图并打开")
    args = ap.parse_args()

    print(f"阶段 1：并发发送 {args.n} 条{'移动小车' if args.act == 'move' else '机械臂'}动作...")
    pool = ThreadPoolExecutor(args.n)
    futs = [pool.submit(burst, i, args.act) for i in range(args.n)]
    time.sleep(2.0)

    print("阶段 2：堆积进行中，状态接口是否还能及时响应...")
    t0 = time.time()
    try:
        r = requests.get(BASE + "/state", timeout=5)
        st = {"status": r.status_code, "sec": round(time.time() - t0, 3)}
    except Exception as e:
        st = {"status": "timeout", "sec": round(time.time() - t0, 3), "err": type(e).__name__}
    print("  /state:", st)

    print("阶段 3：堆积进行中，再发 1 条正常指令，测量要等多久...")
    t0 = time.time()
    try:
        r = requests.post(BASE + ("/move" if args.act == "move" else "/arm"),
                          json=payload(0, args.act), timeout=10)
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
    print("  批量结果:", counts, " 延迟 p50/max:", secs[len(secs) // 2], max(secs))

    # 批量结束后等 2 秒，再取相隔 1 秒的两帧：判断卡死时画面是否还在变化
    time.sleep(2)
    f1 = grab()
    time.sleep(1.0)
    f2 = grab()
    diff = frame_diff(f1, f2)
    frozen = (probe["status"] == "timeout" or probe["sec"] >= 5
              or st["status"] == "timeout" or st["sec"] >= 3)
    summary = {
        "tag": args.tag, "act": args.act, "burst_n": args.n, "burst_status": counts,
        "burst_latency_p50": secs[len(secs) // 2], "burst_latency_max": max(secs),
        "state": st, "probe": probe, "frame_diff_pct": diff,
        "frame_static": (diff is not None and diff < 0.5), "frozen": frozen,
        "verdict": "❌ 卡死已复现：堆积后新指令长时间无响应" if frozen
                   else "✅ 未卡死：堆积被限流，状态与指令仍及时响应",
    }
    os.makedirs("results", exist_ok=True)
    json.dump(summary, open(f"results/pileup_{args.tag}.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.annotate:
        annotate(f2, summary, args.tag)


if __name__ == "__main__":
    main()

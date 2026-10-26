#!/usr/bin/env python3
"""epcare CLI —— 与网页同一套后端接口（ai312 环境运行）。

示例（与毕设文档一致）:
  epcare status
  epcare depth --image samples/livingroom.jpg --out depth.png
  epcare find "蓝色的药盒" --room bedroom --no-grab
  epcare patrol --room livingroom --dry-run
  epcare tidy-rules --household demo_family.txt
  epcare eval --feature f2
"""
import argparse
import io
import json
import os
import sys

import requests

BASE = os.environ.get("EPCARE_API", "http://127.0.0.1:8000")
USER = os.environ.get("EPCARE_USER", "admin")
PWD = os.environ.get("EPCARE_PASS", "admin123")


def session():
    s = requests.Session()
    r = s.post(BASE + "/api/login", json={"username": USER, "password": PWD}, timeout=10)
    r.raise_for_status()
    return s


def cmd_status(args):
    s = session()
    st = s.get(BASE + "/api/control/state", timeout=10).json()
    print(json.dumps(st, ensure_ascii=False, indent=2))


def cmd_depth(args):
    """本地跑深度模型（不依赖服务），输出深度图 PNG。"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend import ml
    data = open(args.image, "rb").read()
    png, depth = ml.depth_map(data)
    with open(args.out, "wb") as f:
        f.write(png)
    import numpy as np
    print(f"已保存 {args.out}；相对深度 min={depth.min():.3f} max={depth.max():.3f}（越大越近）")


def cmd_find(args):
    s = session()
    r = s.post(BASE + "/api/tasks/find", json={"query": args.query}, timeout=120)
    r.raise_for_status()
    d = r.json()
    print(f"查询：{d['query']}  找到 {d['count']} 个")
    for it in d["items"][:10]:
        print(f"  {it['label']:20s} 分数 {it['score']:.3f}  距离≈{it['dist_m']}m  box={it['box']}")
    if args.no_grab:
        print("（--no-grab：只定位，不抓取）")
    if d["count"] == 0:
        print("提示：换个更具体的描述，如带上颜色/位置/所属人")


def cmd_patrol(args):
    s = session()
    rooms = s.get(BASE + "/api/rooms", timeout=10).json()
    match = [r for r in rooms if r["name"] == args.room or str(r["id"]) == args.room]
    if not match:
        print("房间不存在，可选：", [r["name"] for r in rooms])
        sys.exit(1)
    r = s.post(BASE + "/api/tasks/patrol",
               json={"room_id": match[0]["id"], "rehearse": bool(args.dry_run)}, timeout=20)
    r.raise_for_status()
    d = r.json()
    print(f"房间：{d['room']}  状态：{d['status']}")
    print("计划：", " → ".join(d["plan"]))
    print(d.get("note", ""))


def cmd_tidy(args):
    lines = [l.strip() for l in open(args.household, encoding="utf-8") if l.strip()]
    s = session()
    r = s.post(BASE + "/api/rules", json={"examples": lines,
                                         "household": os.path.basename(args.household)}, timeout=300)
    r.raise_for_status()
    d = r.json()
    print(f"模型：{d['model']}\n规则：{d['rules']}")


def cmd_eval(args):
    s = session()
    d = s.get(BASE + "/api/eval", timeout=20).json()
    for k, v in d.items():
        if args.feature and args.feature.upper() not in k.upper():
            continue
        print(k, "→", json.dumps(v, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(prog="epcare", description="EPCare CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    p = sub.add_parser("depth")
    p.add_argument("--image", required=True)
    p.add_argument("--out", default="depth.png")
    p.set_defaults(fn=cmd_depth)

    p = sub.add_parser("find")
    p.add_argument("query")
    p.add_argument("--room", default="")
    p.add_argument("--no-grab", action="store_true")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("patrol")
    p.add_argument("--room", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_patrol)

    p = sub.add_parser("tidy-rules")
    p.add_argument("--household", required=True)
    p.set_defaults(fn=cmd_tidy)

    p = sub.add_parser("eval")
    p.add_argument("--feature", default="")
    p.set_defaults(fn=cmd_eval)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

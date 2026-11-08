#!/usr/bin/env python3
"""重标已采测距图的地面接触点（只点选，不改距离/图片）。

用途：首次采集时点到了物体中心/顶部，重新点每个物体“最底部与地面接触的那一点”。
用法：ai312/bin/python scripts/annotate_ranging_points.py [--csv data/ep_ranging/measurements.csv]
"""
import argparse
import csv
import os
import shutil

import cv2

FIELDS = ["file", "object", "distance_m", "distance_tiles", "surface", "light",
          "u_px", "v_px", "note", "ts"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/ep_ranging/measurements.csv")
    ap.add_argument("--data", default="data/ep_ranging")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    if not rows:
        raise SystemExit("CSV 为空")
    # 备份
    bak = args.csv.replace(".csv", "_before_annotate.csv")
    shutil.copyfile(args.csv, bak)
    print(f"已备份 → {bak}")

    by_file = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    win = "re-annotate: click BOTTOM contact point; ESC=skip"
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    cv2.moveWindow(win, 120, 120)
    state = {"click": None, "exit": False}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["click"] = (int(x), int(y))

    cv2.setMouseCallback(win, on_mouse)
    n_ok = 0
    for fn, group in by_file.items():
        path = os.path.join(args.data, "images", fn)
        img = cv2.imread(path)
        if img is None:
            print("缺图，跳过:", fn)
            continue
        h, w = img.shape[:2]
        for r in group:
            state["click"] = None
            obj = r.get("object", "object")
            dist = r.get("distance_m", "?")
            while True:
                show = img.copy()
                cv2.putText(show, f"{obj}  {dist}m  -> click BOTTOM contact", (10, h - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                if state["click"]:
                    x, y = state["click"]
                    cv2.circle(show, (x, y), 6, (0, 0, 255), -1)
                    cv2.putText(show, f"y={y} (bottom should be here)", (10, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
                cv2.imshow(win, show)
                k = cv2.waitKey(30) & 0xFF
                if k == 27:
                    print(f"  跳过 {fn} {obj}")
                    r["u_px"] = r["v_px"] = ""
                    r["note"] = "skipped"
                    state["exit"] = True
                    break
                if state["click"]:
                    x, y = state["click"]
                    r["u_px"], r["v_px"] = str(x), str(y)
                    r["note"] = ""
                    n_ok += 1
                    print(f"  {fn} {obj} -> ({x},{y})")
                    break
            if state["exit"]:
                break
        if state["exit"]:
            break
    cv2.destroyAllWindows()

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"完成：重标 {n_ok} 个点，CSV 已更新；备份在 {bak}")


if __name__ == "__main__":
    main()

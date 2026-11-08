#!/usr/bin/env python3
"""EP 居家测距数据集采集（阶段 2 · F1 标定）。

每张图记 3–5 个物体：真实距离 + 物体与地面的接触点（点击标注）。
距离可直接输入米（0.5），也可用地砖数（2t，默认 1 块砖 0.6m）。

用法（先 bash start.sh real）:
  ai312/bin/python scripts/collect_ranging_data.py --out data/ep_ranging --n 200
  # 中途可退出，下次从已有图片数继续；--no-gui 只采图不点标注（评测不可用）

数据格式 data/ep_ranging/measurements.csv:
  file,object,distance_m,distance_tiles,surface,light,u_px,v_px,note,ts
"""
import argparse
import csv
import json
import os
import sys
import time

import cv2
import requests

API = os.environ.get("EPCARE_API", "http://127.0.0.1:8000")
USER = os.environ.get("EPCARE_USER", "admin")
PWD = os.environ.get("EPCARE_PASS", "admin123")
SURFACES = ["瓷砖", "木地板", "地毯"]
LIGHTS = ["白天", "夜间开灯"]
FIELDS = ["file", "object", "distance_m", "distance_tiles", "surface", "light",
          "u_px", "v_px", "note", "ts"]


def parse_dist(s, tile_m):
    """'0.5'/'0.5m' -> 0.5m；'2t'/'2砖' -> 2*tile_m。返回 (米, 砖数)。"""
    s = s.strip().lower().replace("米", "m").replace("砖", "t")
    if s.endswith("t"):
        tiles = float(s[:-1])
        return round(tiles * tile_m, 3), tiles
    if s.endswith("m"):
        s = s[:-1]
    m = float(s)
    return round(m, 3), round(m / tile_m, 2)


def migrate_header(path):
    """旧 CSV（无 u/v/note）升级到新表头，保留已有行。"""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    if set(FIELDS).issubset(rows[0].keys()):
        return rows
    print(f"升级 {path} 表头（旧行缺 u/v 标注，评测时会被跳过）")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            r.setdefault("distance_tiles", "")
            r.setdefault("u_px", "")
            r.setdefault("v_px", "")
            r.setdefault("note", "legacy")
            w.writerow({k: r.get(k, "") for k in FIELDS})
    return rows


def click_points(img_path, objects):
    """在图上依次点每个物体的地面接触点；返回 {object: (u,v)}；ESC 放弃。"""
    img = cv2.imread(img_path)
    if img is None:
        return {}
    pts, state = {}, {"cur": None, "done": False}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and state["cur"] is not None:
            pts[state["cur"]] = (int(x), int(y))
            state["done"] = True
            cv2.circle(img, (x, y), 6, (0, 0, 255), -1)
            cv2.putText(img, state["cur"], (x + 8, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    win = "click object-ground contact; ESC=skip"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    for obj in objects:
        state["cur"], state["done"] = obj, False
        while not state["done"]:
            show = img.copy()
            cv2.putText(show, f"click: {obj}  (ESC=skip all)", (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(win, show)
            k = cv2.waitKey(30) & 0xFF
            if k == 27:
                cv2.destroyWindow(win)
                print("  已跳过标注（这张图评测不可用）")
                return pts
    cv2.imshow(win, img)
    cv2.waitKey(500)
    cv2.destroyWindow(win)
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/ep_ranging")
    ap.add_argument("--n", type=int, default=200, help="目标总图片数（含已采）")
    ap.add_argument("--tile-m", type=float, default=0.6, help="一块地砖边长（米），默认 600mm")
    ap.add_argument("--camera-height", type=float, default=0.25)
    ap.add_argument("--camera-pitch", type=float, default=0.0, help="相机下俯角（度），仅记录")
    ap.add_argument("--surface", choices=SURFACES, default=None)
    ap.add_argument("--light", choices=LIGHTS, default=None)
    ap.add_argument("--no-gui", action="store_true", help="无图形界面：只拍图不点标注")
    args = ap.parse_args()

    img_dir = os.path.join(args.out, "images")
    os.makedirs(img_dir, exist_ok=True)
    csv_path = os.path.join(args.out, "measurements.csv")
    rows = migrate_header(csv_path)
    done = len({r["file"] for r in rows if r.get("file")})
    print(f"已采 {done} 张 / 目标 {args.n} 张；地砖 {args.tile_m}m，相机高 {args.camera_height}m，"
          f"俯角 {args.camera_pitch}°")
    if done >= args.n:
        print("已达到目标。")
        return

    meta_path = os.path.join(args.out, "meta.json")
    meta = {"tile_m": args.tile_m, "camera_height_m": args.camera_height,
            "camera_pitch_deg": args.camera_pitch, "sessions": []}
    if os.path.exists(meta_path):
        try:
            meta.update(json.load(open(meta_path)))
        except Exception:
            pass
    meta.update({"tile_m": args.tile_m, "camera_height_m": args.camera_height,
                 "camera_pitch_deg": args.camera_pitch})
    meta["sessions"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "start_images": done, "target": args.n})
    json.dump(meta, open(meta_path, "w"), ensure_ascii=False, indent=2)

    s = requests.Session()
    s.post(API + "/api/login", json={"username": USER, "password": PWD}, timeout=10).raise_for_status()
    surface = args.surface
    light = args.light
    if surface is None:
        surface = input(f"本次地面 {SURFACES[0]}/{SURFACES[1]}/{SURFACES[2]}（回车=瓷砖）: ").strip() or SURFACES[0]
    if light is None:
        light = input(f"本次光照 {LIGHTS[0]}/{LIGHTS[1]}（回车=白天）: ").strip() or LIGHTS[0]

    new = not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0
    k = done
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while k < args.n:
            cmd = input(f"\n[{k+1}/{args.n}] 回车拍照（q 退出）: ").strip()
            if cmd.lower() == "q":
                break
            try:
                frame = s.get(API + "/api/control/frame.jpg", timeout=10).content
                if len(frame) < 10000:
                    raise RuntimeError(f"画面太小（{len(frame)} 字节），控制服务可能没画面")
            except Exception as e:
                print("拍不到画面（控制服务未连接？）:", e)
                continue
            fn = f"{int(time.time())}_{k:03d}.jpg"
            path = os.path.join(img_dir, fn)
            open(path, "wb").write(frame)

            spec = input("  物体:距离（如 水瓶:1.2 盒子:2t 收纳包:0.5）: ").strip()
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
                try:
                    m, tiles = parse_dist(d, args.tile_m)
                except ValueError:
                    print(f"  距离格式不对，跳过 {o}:{d}")
                    continue
                pairs.append((o.strip(), m, tiles))
            if not pairs:
                print("  没输入有效物体，删除本张")
                os.remove(path)
                continue

            pts = {} if args.no_gui else click_points(path, [p[0] for p in pairs])
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")
            for obj, m, tiles in pairs:
                u, v = pts.get(obj, ("", ""))
                w.writerow({"file": fn, "object": obj, "distance_m": f"{m:.3f}",
                            "distance_tiles": f"{tiles:.2f}", "surface": surface,
                            "light": light, "u_px": u, "v_px": v,
                            "note": "" if (u != "" and v != "") else "no_point", "ts": ts})
            f.flush()
            k += 1
            print(f"  已保存 {fn}，{len(pairs)} 个物体"
                  + ("" if pts else "（无标注，评测跳过）"))

    # 收尾统计
    with open(csv_path, newline="", encoding="utf-8") as f:
        allrows = list(csv.DictReader(f))
    usable = [r for r in allrows if r.get("u_px") and r.get("v_px")]
    print(f"\n完成：{len({r['file'] for r in allrows})} 张图、{len(allrows)} 条物体记录，"
          f"其中 {len(usable)} 条有地面接触点可评测。")
    for key in ("surface", "light"):
        cnt = {}
        for r in allrows:
            cnt[r.get(key, "?")] = cnt.get(r.get(key, "?"), 0) + 1
        print(f"  {key}: {cnt}")


if __name__ == "__main__":
    main()

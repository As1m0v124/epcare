#!/usr/bin/env python3
"""拍照标定过程演示（回放真机 9 张 pilot，或 --synthetic 用合成点）。

过程：逐张显示照片 → 十字准星移到物体底部接触点 → “拍照” → 记录距离 →
右侧累计样本并实时拟合 Z=a/(v-y_h) → 最后给出 A/B/C 对比。

输出 results/calibration_demo/：
  photo_calibration_demo.gif   逐张过程动画
  photo_calibration_demo.mp4   同样内容的视频（若 OpenCV 编码可用）
  photo_calibration_demo.json  演示数据源/参数

用法:
  ai312/bin/python scripts/demo_calibration_photos.py            # 真机 9 张 pilot 回放
  ai312/bin/python scripts/demo_calibration_photos.py --synthetic # 纯合成演示
  ai312/bin/python scripts/demo_calibration_photos.py --open      # 生成后打开 GIF
"""
import argparse
import csv
import io
import json
import math
import os
import subprocess

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
plt.rcParams["font.family"] = "Hiragino Sans GB"
plt.rcParams["axes.unicode_minus"] = False


def fp(size):
    return font_manager.FontProperties(fname=FONT, size=size)


def fit_row(v, z, h):
    best = None
    for yh in np.arange(-3.0 * h, 2.0 * h, 1.0):
        den = v - yh
        if np.any(np.abs(den) < 1e-6):
            continue
        r = 1.0 / den
        a = float((z * r).sum() / (r * r).sum())
        if a <= 0:
            continue
        rmse = float(np.sqrt(np.mean((a * r - z) ** 2)))
        if best is None or rmse < best[0]:
            best = (rmse, a, float(yh))
    return (best[1], best[2]) if best else (None, None)


def absrel(z, gt):
    z, gt = np.asarray(z, float), np.asarray(gt, float)
    ok = (z > 0) & np.isfinite(z)
    return float(np.mean(np.abs(z[ok] - gt[ok]) / gt[ok])) if ok.any() else None


def load_points(args):
    if not args.synthetic:
        csv_path = os.path.join(ROOT, "data", "ep_ranging", "measurements.csv")
        img_dir = os.path.join(ROOT, "data", "ep_ranging", "images")
        rows = []
        if os.path.exists(csv_path):
            for r in csv.DictReader(open(csv_path, encoding="utf-8")):
                try:
                    u, v = float(r["u_px"]), float(r["v_px"])
                    z = float(r["distance_m"])
                except (KeyError, ValueError):
                    continue
                p = os.path.join(img_dir, r["file"])
                if z > 0 and os.path.exists(p):
                    rows.append({"img": p, "u": u, "v": v, "z": z,
                                 "object": r.get("object", ""), "file": r["file"]})
        if rows:
            rows.sort(key=lambda x: (round(x["z"], 2), x["object"]))
            return rows, "real", "真机 9 张 pilot 回放"

    # 合成：用一张 EP 实拍当背景，按地面模型生成 12 个点
    bg = os.path.join(ROOT, "results", "patrol", "loop_24_1.jpg")
    rng = np.random.default_rng(11)
    rows = []
    for k, z0 in enumerate([0.6, 1.2, 1.8, 2.4]):
        for j in range(3):
            z = z0 * (1 + rng.normal(0, 0.01))
            v = -12 + 90.0 / z + rng.normal(0, 1.2)
            u = 320 + rng.normal(0, 25)
            rows.append({"img": bg, "u": u, "v": v, "z": z,
                         "object": ["水瓶", "盒子", "收纳包"][j], "file": "synthetic"})
    rows.sort(key=lambda x: (round(x["z"], 2), x["object"]))
    return rows, "synthetic", "合成演示（不是真机结果）"


def render_frame(row, idx, total, samples, clicked, cross, source_label, final=False, flash=False):
    fig = plt.figure(figsize=(16, 9), facecolor="#0f141b")
    ax = fig.add_axes([0.015, 0.09, 0.58, 0.82]); ax.set_facecolor("#0f141b")
    img = np.asarray(Image.open(row["img"]).convert("RGB"))
    h, w = img.shape[:2]
    ax.imshow(img); ax.set_xlim(0, w); ax.set_ylim(h, 0); ax.axis("off")
    if flash:
        ax.add_patch(Rectangle((0, 0), w, h, facecolor="white", alpha=0.35))
        ax.text(w / 2, h / 2, f"拍照 · 记录真实距离 {row['z']:.2f}m", ha="center", va="center",
                color="#111", fontproperties=fp(22),
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 8, "alpha": 0.9})

    # 照片标题 + 提示
    ax.text(10, 24, f"第 {idx+1}/{total} 张 · {row['object']} · 真实距离 {row['z']:.2f}m",
            color="white", fontproperties=fp(17),
            bbox={"facecolor": (0, 0, 0, 0.65), "edgecolor": "none", "pad": 4})
    tip = ("标定完成：已记录全部样本" if final else
           "已记录接触点" if clicked else "点击物体最底部与地面接触的那一点")
    ax.text(10, h - 12, tip,
            color="#66d9ff" if not clicked else "#00e0a4", fontproperties=fp(14),
            bbox={"facecolor": (0, 0, 0, 0.6), "edgecolor": "none", "pad": 3})

    # 十字准星 / 点击点
    if cross is not None:
        cx, cy = cross
        ax.plot([cx], [cy], marker="+", markersize=28, markeredgewidth=2,
                color="#ffd166")
    if clicked:
        ax.scatter([row["u"]], [row["v"]], s=130, facecolors="none",
                   edgecolors="#ff5c5c", linewidths=2.5)
        ax.annotate(f"({row['u']:.0f},{row['v']:.0f})", (row["u"], row["v"]),
                    xytext=(12, 18), textcoords="offset points",
                    color="#ff5c5c", fontproperties=fp(12),
                    bbox={"facecolor": (0, 0, 0, 0.55), "edgecolor": "none", "pad": 2})

    # 右侧：累计样本 + 拟合
    ax2 = fig.add_axes([0.63, 0.13, 0.35, 0.75]); ax2.set_facecolor("#0f141b")
    if samples:
        vs = np.array([p["v"] for p in samples]); zs = np.array([p["z"] for p in samples])
        ax2.scatter(vs, zs, s=45, c="#66d9ff", zorder=3, label=f"已采样 {len(samples)} 点")
        if len(samples) >= 5:
            a, yh = fit_row(vs, zs, h)
            if a:
                vv = np.linspace(5, 175, 300)
                ax2.plot(vv, a / (vv - yh), c="#00e0a4", lw=2.5,
                         label=f"B: Z={a:.1f}/(v-({yh:.1f}))")
                pred = a / (vs - yh)
                er = absrel(pred, zs)
                ax2.text(0.03, 0.06, f"累计拟合 AbsRel {er*100:.2f}%",
                         transform=ax2.transAxes, color="#00e0a4", fontproperties=fp(13))
    ax2.axvspan(0, 180, color="#ff5c5c", alpha=0.06)
    ax2.axvline(180, color="#ff5c5c", ls="--", lw=1)
    ax2.text(8, 2.9, "A 固定针孔：\nv<180 全部无定义", color="#ff6b6b",
             fontproperties=fp(11), va="top")
    ax2.set_xlim(0, 190); ax2.set_ylim(0, 3.0)
    ax2.set_xlabel("接触点行号 v (px)", color="#ddd", fontproperties=fp(12))
    ax2.set_ylabel("真实距离 Z (m)", color="#ddd", fontproperties=fp(12))
    ax2.tick_params(colors="#aaa"); ax2.grid(alpha=0.15)
    if samples:
        ax2.legend(prop=fp(11), facecolor="#1b2028", labelcolor="white", loc="upper right")
    ax2.set_title("标定过程：采样 → 拟合", color="white", fontproperties=fp(16))


    title = (f"标定完成 · 真机 held-out B 3.04% / C 3.21% · {source_label}"
             if final else f"拍照标定过程演示 · {source_label} · 回放，不是新采集")
    fig.suptitle(title, color="#ffb347", fontproperties=fp(19), y=0.975)
    fig.text(0.5, 0.02, "演示用途；真机标定结果见 results/ep_ranging_eval.md",
             ha="center", color="#ffb347", fontproperties=fp(11))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "calibration_demo"))
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rows, source, label = load_points(args)
    if not rows:
        raise SystemExit("没有可用照片/点；先采 9 张或加 --synthetic")

    frames, durs = [], []
    samples = []
    total = len(rows)
    for i, row in enumerate(rows):
        h = Image.open(row["img"]).height
        # 准星从画面上部移到底部接触点
        for t in (0.0, 0.45, 0.8):
            cx = row["u"]
            cy = (h * 0.45) * (1 - t) + row["v"] * t
            frames.append(render_frame(row, i, total, samples, False, (cx, cy), label))
            durs.append(350)
        # 拍照闪光 + 点击
        frames.append(render_frame(row, i, total, samples, False, (row["u"], row["v"]), label))
        durs.append(300)
        frames.append(render_frame(row, i, total, samples, False, None, label, flash=True))
        durs.append(300)
        samples.append(row)
        frames.append(render_frame(row, i, total, samples, True, None, label))
        durs.append(650)

    # 收尾：全部样本 + 拟合
    final = render_frame(rows[-1], total - 1, total, samples, False, None, label, final=True)
    frames.append(final); durs.append(2200)

    gif = os.path.join(args.out, "photo_calibration_demo.gif")
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=durs, loop=0,
                   optimize=True)

    # 可选 mp4（OpenCV 编码）
    mp4 = os.path.join(args.out, "photo_calibration_demo.mp4")
    try:
        import cv2
        w, h = frames[0].size
        writer = cv2.VideoWriter(mp4, cv2.VideoWriter_fourcc(*"mp4v"), 2.5, (w, h))
        for im in frames:
            writer.write(cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR))
        writer.release()
    except Exception:
        mp4 = None

    # 汇总
    vs = np.array([p["v"] for p in samples]); zs = np.array([p["z"] for p in samples])
    a, yh = fit_row(vs, zs, 360)
    summary = {
        "source": source, "source_label": label, "n_photos": len(samples),
        "objects": [p["object"] for p in samples],
        "distances_m": [round(float(p["z"]), 3) for p in samples],
        "points": [{"v": round(float(p["v"]), 1), "z": round(float(p["z"]), 3)} for p in samples],
        "fit": {"a": a, "y_h": yh, "note": "累计 9 点 in-sample 拟合，演示用"},
        "warning": "回放/合成演示，不是新采集；最终精度见 results/ep_ranging_eval.md",
    }
    json.dump(summary, open(os.path.join(args.out, "photo_calibration_demo.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"数据源: {label}（{len(samples)} 张）")
    print(f"拟合: a={a:.2f}, y_h={yh:.1f}（累计 in-sample，演示用）")
    print(f"输出: {gif}" + (f" / {mp4}" if mp4 else ""))
    if args.open and sys_platform() == "darwin":
        subprocess.Popen(["open", gif])


def sys_platform():
    import sys
    return sys.platform


if __name__ == "__main__":
    main()

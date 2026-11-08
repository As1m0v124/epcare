#!/usr/bin/env python3
"""模拟测距标定过程（演示用，合成数据，不是真机结果）。

生成一层地平面（相机下俯、地平线在画面外），模拟“点物体底部接触点 + 记录真实距离”，
演示：
  ① 固定针孔（俯角 0）为什么失效；
  ② 地平面标定 Z=a/(v-y_h) 如何拟合；
  ③ 采样从 1 张到 200 张时，误差如何收敛。

输出 results/calibration_demo/：
  calibration_demo.png   三栏说明图
  calibration_demo.gif   采样收敛动画（可直接放视频）
  calibration_demo.json  演示参数与误差（标注 simulated=true）

用法: ai312/bin/python scripts/demo_calibration.py
"""
import argparse
import json
import os

import numpy as np
from PIL import Image
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
plt.rcParams["font.family"] = "Hiragino Sans GB"
plt.rcParams["axes.unicode_minus"] = False
from matplotlib.patches import Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def fp(size):
    try:
        return font_manager.FontProperties(fname=FONT, size=size)
    except Exception:
        return font_manager.FontProperties(size=size)


def fit_row(v, z, h):
    """Z = a/(v-y_h)：网格搜 y_h，闭式解 a。"""
    best = None
    for yh in np.arange(-3.0 * h, 2.0 * h, 1.0):
        den = v - yh
        if np.any(np.abs(den) < 1e-6):
            continue
        r = 1.0 / den
        a = float((z * r).sum() / (r * r).sum())
        if a <= 0:
            continue
        pred = a * r
        rmse = float(np.sqrt(np.mean((pred - z) ** 2)))
        if best is None or rmse < best[0]:
            best = (rmse, a, float(yh))
    return (best[1], best[2]) if best else (None, None)


def metrics(z, gt):
    z = np.asarray(z, float); gt = np.asarray(gt, float)
    ok = z > 0
    if ok.sum() == 0:
        return {"n": 0}
    z, gt = z[ok], gt[ok]
    return {"n": int(ok.sum()),
            "absrel": round(float(np.mean(np.abs(z - gt) / gt)), 4),
            "rmse_m": round(float(np.sqrt(np.mean((z - gt) ** 2))), 4),
            "delta1": round(float(np.mean(np.maximum(z / gt, gt / z) < 1.25)), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "calibration_demo"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-max", type=int, default=200)
    ap.add_argument("--no-gif", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    # 合成“真值”：相机下俯，地平线在画面外（y=-12），H=0.25m，f=212px
    H, H_IMG, Y_H, A_ROW = 360, 360, -12.0, 90.0
    levels = np.array([0.6, 1.2, 1.8])
    n_img = args.n_max
    rows, dists, disp, files = [], [], [], []
    for i in range(n_img):
        for z0 in levels:
            z = z0 * (1 + rng.normal(0, 0.008))                 # 摆放误差
            v = Y_H + A_ROW / z + rng.normal(0, 1.2)            # 点击底部接触点 ±1.2px
            u = 320 + rng.normal(0, 22)                          # 横向位置
            d = (1.0 / z - 0.033) / 0.85 * (1 + rng.normal(0, 0.02))  # 深度相对值
            rows.append(v); dists.append(z); disp.append(d); files.append(i)
    rows, dists, disp, files = map(np.array, (rows, dists, disp, files))

    # 固定测试集（每距离 40 个点），与训练采样独立
    tr_rows, tr_z = rows[:60], dists[:60]
    test_idx = rng.choice(len(rows), 120, replace=False)
    te_rows, te_z, te_disp = rows[test_idx], dists[test_idx], disp[test_idx]
    test_bank = (te_rows, te_z, te_disp)

    # A：固定针孔（地平线在画面中心，俯角 0）
    def fixed_z(v):
        dv = v - H_IMG / 2
        return 212.0 * 0.25 / dv if dv > 10 else None
    a_pred = np.array([fixed_z(v) if fixed_z(v) else np.nan for v in te_rows])
    valid = ~np.isnan(a_pred)
    a_res = metrics(a_pred[valid], te_z[valid])

    # B：用全部 600 点拟合（最终演示值）
    a_b, yh_b = fit_row(rows, dists, H_IMG)
    b_pred = np.where(te_rows - yh_b > 1e-6, a_b / (te_rows - yh_b), np.nan)
    b_res = metrics(b_pred, te_z)

    # C：1/Z = a*disp + b
    Ac = np.stack([disp, np.ones_like(disp)], 1)
    (ac, bc), *_ = np.linalg.lstsq(Ac, 1.0 / dists, rcond=None)
    c_pred = 1.0 / (ac * te_disp + bc)
    c_res = metrics(c_pred, te_z)

    summary = {
        "simulated": True, "note": "合成数据演示，不是真机标定结果",
        "camera": {"H_m": 0.25, "f_px": 212, "horizon_row": Y_H, "pitch": "下俯（地平线在画面外）"},
        "n_images": int(n_img), "n_points": int(len(rows)),
        "A_fixed_pinhole": a_res, "B_ground_fit": {**b_res, "a": a_b, "y_h": yh_b},
        "C_depth_fit": {**c_res, "a": round(float(ac), 4), "b": round(float(bc), 4)},
        "real_pilot_reference": {"B_absrel": 0.0304, "C_absrel": 0.0321,
                                 "source": "results/ep_ranging_eval.md（9 张真机，非本演示）"},
    }
    json.dump(summary, open(os.path.join(args.out, "calibration_demo.json"), "w"),
              ensure_ascii=False, indent=2)

    # ---------- 静态三栏图 ----------
    fig = plt.figure(figsize=(16, 9), facecolor="#11151c")
    gs = fig.add_gridspec(1, 3, width_ratios=[1.1, 1.15, 0.9], wspace=0.25)
    fig.suptitle("模拟标定过程（合成数据 · 演示用，不是真机结果）",
                 color="#ffb347", fontproperties=fp(24), y=0.97)

    # ① 采集示意：EP 实拍背景 + 合成接触点
    ax = fig.add_subplot(gs[0, 0]); ax.set_facecolor("#11151c")
    bg_path = os.path.join(ROOT, "results", "patrol", "loop_24_1.jpg")
    if os.path.exists(bg_path):
        ax.imshow(np.asarray(Image.open(bg_path).convert("RGB")))
    ax.set_xlim(0, 640); ax.set_ylim(360, 0); ax.axis("off")
    ax.set_title("① 采集：点物体底部接触点（示意图）", color="white", fontproperties=fp(16))
    for z0, color in zip(levels, ["#66d9ff", "#ffd166", "#ff7b7b"]):
        v = Y_H + A_ROW / z0
        ax.scatter([320], [v], s=90, facecolors="none", edgecolors=color, linewidths=2)
        dy = {-1: -26, 0: 22, 1: 26}[int(round((z0 - 1.2) / 0.6))]
        ax.annotate(f"{z0:.1f}m", (320, v), xytext=(340, v + dy),
                    color=color, fontproperties=fp(12),
                    arrowprops={"arrowstyle": "-", "color": color, "lw": 1})
    ax.text(12, 338, "背景为 EP 实拍，点位为合成", color="#ffb347",
            fontproperties=fp(11), va="bottom")

    # ② 地平面拟合
    ax = fig.add_subplot(gs[0, 1]); ax.set_facecolor("#11151c")
    ax.scatter(rows, dists, s=8, c="#4d7ea8", alpha=0.35, label="采样点（600）")
    vv = np.linspace(5, 175, 400)
    ax.plot(vv, a_b / (vv - yh_b), c="#00e0a4", lw=2.5,
            label=f"B 拟合  Z={a_b:.1f}/(v-({yh_b:.1f}))")
    ax.axvspan(0, 180, color="#ff5c5c", alpha=0.06)
    ax.axvline(180, color="#ff5c5c", ls="--", lw=1)
    ax.text(8, 2.55, "A 固定针孔在这里\n全部无定义（v<180）", color="#ff6b6b",
            fontproperties=fp(12), va="top")
    ax.set_xlim(0, 190); ax.set_ylim(0, 3.0)
    ax.set_xlabel("接触点行号 v (px)", color="#ddd"); ax.set_ylabel("真实距离 Z (m)", color="#ddd")
    ax.set_title("② 地平面标定：行号 → 距离", color="white", fontproperties=fp(16))
    ax.tick_params(colors="#aaa"); ax.grid(alpha=0.15)
    ax.legend(prop=fp(11), facecolor="#1b2028", labelcolor="white", loc="upper right")

    # ③ 误差对比
    ax = fig.add_subplot(gs[0, 2]); ax.set_facecolor("#11151c")
    names = ["A 固定针孔", "B 地平面", "C 深度"]
    vals = [0.0, b_res.get("absrel", 0) * 100, c_res.get("absrel", 0) * 100]
    colors = ["#555", "#00e0a4", "#4dabf7"]
    bars = ax.bar(names, vals, color=colors)
    ax.text(0, 2, "不可用\n(0 个有效点)", ha="center", color="#ff6b6b", fontproperties=fp(11))
    for b, v in zip(bars[1:], vals[1:]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.15, f"{v:.2f}%",
                ha="center", color="white", fontproperties=fp(12))
    ax.set_ylim(0, max(5, max(vals) * 1.35))
    ax.set_ylabel("测试 AbsRel (%)", color="#ddd")
    ax.set_title("③ 误差对比（合成）", color="white", fontproperties=fp(16))
    ax.tick_params(colors="#aaa"); ax.grid(axis="y", alpha=0.15)
    ax.text(0.02, 0.97, "真机 9 张 pilot（参考）\nB 3.04% · C 3.21%\n（非本演示数据）",
            transform=ax.transAxes, va="top", color="#ffb347", fontproperties=fp(10))

    fig.text(0.5, 0.02, "合成演示 · 不是真机标定结果；真机结果见 results/ep_ranging_eval.md",
             ha="center", color="#ffb347", fontproperties=fp(12))
    png = os.path.join(args.out, "calibration_demo.png")
    fig.savefig(png, dpi=110, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)

    # ---------- 采样收敛动画 ----------
    gif_path = os.path.join(args.out, "calibration_demo.gif")
    if not args.no_gif:
        frames, durs = [], []
        ns = [1, 2, 3, 5, 9, 15, 25, 50, 100, 200]
        for k, n in enumerate(ns):
            idx = np.arange(min(n * 3, len(rows)))
            v, z = rows[idx], dists[idx]
            fig2, ax2 = plt.subplots(figsize=(12.8, 7.2), facecolor="#11151c")
            ax2.set_facecolor("#11151c")
            ax2.scatter(v, z, s=22, c="#66d9ff", alpha=0.9, label=f"已采样 {len(idx)} 点（{n} 张图）")
            if len(idx) >= 5:
                aa, yy = fit_row(v, z, H_IMG)
                vv2 = np.linspace(5, 175, 400)
                ax2.plot(vv2, aa / (vv2 - yy), c="#00e0a4", lw=2.5, label="B 拟合")
                pred = aa / (te_rows - yy)
                r = metrics(pred, te_z)
                info = f"采样 {n} 张｜测试 AbsRel {r['absrel']*100:.2f}%｜y_h={yy:.1f}"
            else:
                info = f"采样 {n} 张｜样本不足，无法拟合"
            ax2.set_xlim(0, 190); ax2.set_ylim(0, 3.0)
            ax2.set_xlabel("接触点行号 v (px)", color="#ddd"); ax2.set_ylabel("真实距离 Z (m)", color="#ddd")
            ax2.tick_params(colors="#aaa"); ax2.grid(alpha=0.15)
            ax2.legend(prop=fp(11), facecolor="#1b2028", labelcolor="white", loc="upper right")
            ax2.set_title("模拟标定：采样 → 拟合 → 误差收敛（合成数据）", color="white",
                          fontproperties=fp(18), pad=16)
            ax2.text(0.02, 0.95, info, transform=ax2.transAxes, va="top",
                     color="#00e0a4", fontproperties=fp(14))
            fig2.text(0.5, 0.02, "演示用合成数据，不是真机标定结果",
                      ha="center", color="#ffb347", fontproperties=fp(12))
            tmp = os.path.join(args.out, f"_frame_{k:02d}.png")
            fig2.savefig(tmp, dpi=100, facecolor=fig2.get_facecolor(), bbox_inches="tight")
            plt.close(fig2)
            frames.append(Image.open(tmp).convert("RGB"))
            durs.append(700 if k < len(ns) - 1 else 1800)
        frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                       duration=durs, loop=0, optimize=True)
        for k in range(len(ns)):
            try:
                os.remove(os.path.join(args.out, f"_frame_{k:02d}.png"))
            except OSError:
                pass

    print("=== 模拟标定演示（合成数据，仅演示流程）===")
    print(f"相机: f=212px, H=0.25m, 地平线 y={Y_H}px（下俯，画面外）")
    print(f"数据: {n_img} 张 × 3 物体 = {len(rows)} 点，点击噪声 σ=1.2px")
    print(f"A 固定针孔: {a_res.get('n',0)}/120 个测试点可用（v<180 全部无定义）")
    print(f"B 地平面: a={a_b:.2f}, y_h={yh_b:.1f}, AbsRel={b_res.get('absrel')}")
    print(f"C 深度: a={ac:.3f}, b={bc:.3f}, AbsRel={c_res.get('absrel')}")
    print(f"真机 9 张 pilot（参考，非本演示）: B 3.04% / C 3.21%")
    print(f"输出: {png}" + (f"，{gif_path}" if not args.no_gif else ""))


if __name__ == "__main__":
    main()

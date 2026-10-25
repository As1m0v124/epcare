#!/usr/bin/env python3
"""week1.py — 一条命令跑完第 1 周全部指标（毕设第 11 节第 7 条要求）。

依次输出:
  F1  NYU-D 654 张测试集 AbsRel / delta1（对照 0.053 / 0.973）
  F2  COCO val2017 前 500 张零样本 AP（对照 48.4）
  F3  TidyBot 基准前 20 个场景两种方法准确率（对照 78.5% / 91.2%）

已有结果文件默认跳过，--force 强制重跑。
真机自检（ep_selfcheck.py）需机器人在线，不在此脚本内。

用法: ai312/bin/python week1.py [--force]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RES = os.path.join(HERE, "results")


def have(path, min_size=0):
    return os.path.exists(path) and os.path.getsize(path) > min_size


def run_step(name, args, out, force):
    out_path = os.path.join(RES, out)
    if have(out_path) and not force:
        print(f"[{name}] 已有结果，跳过（--force 重跑）")
        return json.load(open(out_path))
    print(f"\n[{name}] 开始运行 ...")
    code = subprocess.call([PY] + args, cwd=HERE)
    if code != 0 or not have(out_path):
        print(f"[{name}] ❌ 未产出结果")
        return None
    return json.load(open(out_path))


def main():
    force = "--force" in sys.argv
    os.makedirs(RES, exist_ok=True)
    summary = {}

    # F1 依赖完整 NYU mat
    nyu = os.path.join(HERE, "data", "NYUv2", "nyu_depth_v2_labeled.mat")
    if have(nyu, 2900000000):
        summary["f1"] = run_step("F1 NYU-D", ["scripts/eval_depth_nyu.py"],
                                 "nyu_f1.json", force)
    else:
        print("[F1] ⏳ 数据未就绪（data/NYUv2/nyu_depth_v2_labeled.mat 不完整），跳过")

    # F2：官方 val2017 或 parquet 转换版均可
    imgs = os.path.join(HERE, "data", "coco", "val2017")
    n_imgs = len([f for f in os.listdir(imgs) if f.endswith(".jpg")]) if os.path.isdir(imgs) else 0
    if n_imgs >= 100:
        summary["f2"] = run_step("F2 COCO-500", ["scripts/eval_gdino_coco500.py", "--limit", "500"],
                                 "coco_f2.json", force)
    else:
        print(f"[F2] ⏳ COCO 图片未就绪（现有 {n_imgs} 张），跳过")

    # F3：本地模型与基准就绪即可
    model_dir = os.path.join(HERE, "models", "qwen2.5-3b")
    if os.path.isdir(model_dir) and any(f.endswith(".safetensors") for f in os.listdir(model_dir)):
        summary["f3"] = run_step("F3 TidyBot-20", ["scripts/eval_tidybot.py", "--n", "20"],
                                 "tidybot_f3.json", force)
    else:
        print("[F3] ⏳ 本地模型未就绪，跳过")

    # 照片演示：EP 实拍 10 张 → 深度图 + 检测 CSV（第 11 节第 7 条最后一项）
    ph_dir = os.path.join(HERE, "results", "selfcheck_photos")
    photos = [f for f in os.listdir(ph_dir)] if os.path.isdir(ph_dir) else []
    photos = [f for f in photos if f.endswith(".jpg")]
    if photos:
        summary["photos"] = run_step("照片演示(深度+检测)", ["scripts/week1_photos_demo.py"],
                                     "photos_demo/photos_demo.json", force)
    else:
        print("[照片] ⏳ 无 EP 实拍照片（先跑 ep_selfcheck.py），跳过")

    # 汇总对照表
    print("\n" + "=" * 62)
    print("第 1 周指标汇总（对照论文）")
    print("=" * 62)
    f1 = summary.get("f1") or {}
    if f1:
        print(f"F1 AbsRel   {f1.get('abs_rel')}   论文 0.053")
        print(f"F1 delta1   {f1.get('delta1')}   论文 0.973")
    f2 = summary.get("f2") or {}
    if f2:
        print(f"F2 AP       {f2.get('AP')}   论文 48.4（前 {f2.get('n_images')} 张）")
    f2full_path = os.path.join(RES, "coco_f2_full.json")
    if os.path.exists(f2full_path):
        ff = json.load(open(f2full_path))
        summary["f2_full"] = ff
        print(f"F2 全量 AP  {ff.get('AP')}   AP50 {ff.get('AP50')}（{ff.get('n_images')} 张）")
    f3 = summary.get("f3") or {}
    if f3:
        print(f"F3 只看示例     {f3.get('examples_only_acc')}%   论文 78.5%")
        print(f"F3 先归纳再推断 {f3.get('summarization_acc')}%   论文 91.2%")
    ph = summary.get("photos") or {}
    if ph:
        print(f"照片演示       {ph.get('n_photos')} 张, 检测 {ph.get('n_detections')} 个 -> results/photos_demo/")
    print("=" * 62)

    json.dump(summary, open(os.path.join(RES, "week1_summary.json"), "w"),
              ensure_ascii=False, indent=2)
    print("汇总已保存: results/week1_summary.json")


if __name__ == "__main__":
    main()

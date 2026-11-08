#!/usr/bin/env python3
"""把 20 张测距 pilot 的评测结果写入 11/10 进度报告的标记区。

用法（采完 20 张并跑完 eval_ep_ranging.py 后）:
  ai312/bin/python scripts/update_report_pilot.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "submission", "2026-11-10", "01_进度报告.md")
EVAL_MD = os.path.join(ROOT, "results", "ep_ranging_eval.md")
EVAL_JSON = os.path.join(ROOT, "results", "ep_ranging_eval.json")
START, END = "<!-- PILOT_START -->", "<!-- PILOT_END -->"


def main():
    rep = open(REPORT, encoding="utf-8").read()
    if START not in rep or END not in rep:
        raise SystemExit("报告里找不到 PILOT_START/PILOT_END 标记")
    if not os.path.exists(EVAL_MD):
        raise SystemExit("没有 results/ep_ranging_eval.md，先跑 scripts/eval_ep_ranging.py")
    md_lines = [ln for ln in open(EVAL_MD, encoding="utf-8").read().splitlines()
                if not ln.startswith("# ")]
    md = "\n".join(md_lines).strip()
    ev = json.load(open(EVAL_JSON, encoding="utf-8")) if os.path.exists(EVAL_JSON) else {}
    a = ev.get("A_fixed_pinhole", {})
    b = ev.get("B_ground_calibrated", {})
    c = ev.get("C_depth_calibrated", {})
    conclusion = ["", "**结论**："]
    if a.get("absrel") is None or a.get("n", 0) == 0:
        conclusion.append("A 固定针孔 0 个点可用（地面接触点都在画面中线以上，俯角 0 的假设不成立）；")
    elif b.get("absrel") is not None:
        conclusion.append(f"B 地平面标定 AbsRel {b['absrel']}，A 固定针孔 {a['absrel']}；")
    if b.get("absrel") is not None:
        conclusion.append(f"B 地平面标定 AbsRel {b['absrel']}（RMSE {b.get('rmse_m')}m，δ1 {b.get('delta1')}）；")
    if c.get("absrel") is not None:
        conclusion.append(f"C 深度标定 AbsRel {c['absrel']}（RMSE {c.get('rmse_m')}m，δ1 {c.get('delta1')}）；")
    conclusion.append("本次 pilot 9 张（时间限制），只验证采集/评测管线；200 张采满后再定最终标定参数。")
    block = "**采集/评测结果**：\n\n" + md + "\n\n" + "".join(conclusion)
    rep = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 START + "\n" + block + "\n" + END, rep, flags=re.S)
    open(REPORT, "w", encoding="utf-8").write(rep)
    print("已写入报告：", REPORT)


if __name__ == "__main__":
    main()

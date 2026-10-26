#!/usr/bin/env python3
"""F3: TidyBot 偏好基准（前 20 个场景）上复算「只看示例」与「先归纳再推断」。

对照论文 Table 2: 只看示例 78.5% / 先归纳再推断 91.2%（96 场景，未见过的物品）。

实现说明:
  - 提示词与解析完全沿用 TidyBot 官方 benchmark（third_party/tidybot/benchmark/*.ipynb 移植）；
  - 论文用已停用的 OpenAI Completion 接口；本机改用 Qwen2.5-3B-Instruct 本地模型
    （ModelScope 下载，零成本离线运行；模型与论文不同，按毕设要求写明该差异）；
  - 评分口径同官方 check_placements：未见过物品放对位置的比例。

用法:
  ai312/bin/python scripts/eval_tidybot.py                       # 前 20 场景，两种方法
  ai312/bin/python scripts/eval_tidybot.py --n 5                 # 冒烟测试
  ai312/bin/python scripts/eval_tidybot.py --model qwen2.5:3b-instruct
"""
import argparse
import csv
import json
import os
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_DIR = os.path.join(HERE, "third_party", "tidybot", "benchmark")
sys.path.insert(0, BENCH_DIR)
import benchmark  # noqa: E402


class LocalLLM:
    """本地小模型（Qwen2.5-3B-Instruct，ModelScope 下载），禁止采样保证可复现。"""

    def __init__(self, path):
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForCausalLM.from_pretrained(
            path, torch_dtype=torch.float16, low_cpu_mem_usage=True
        ).to("mps" if torch.backends.mps.is_available() else "cpu").eval()
        self.device = self.model.device

    def gen(self, prompt, max_new_tokens=160):
        ids = self.tok(prompt, return_tensors="pt", truncation=True, max_length=2048).to(self.device)
        with torch.no_grad():
            out = self.model.generate(
                **ids, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=self.tok.eos_token_id,
            )
        text = self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        # 与原 benchmark 行为一致：遇到空行即截断
        return text.split("\n\n")[0]



# ---------- 官方提示词（逐字移植自 notebooks） ----------
def placements_examples_only(sc, objects):
    seen = "[" + ", ".join(f'"{x}"' for x in sc.seen_objects) + "]"
    recep = "[" + ", ".join(f'"{x}"' for x in sc.receptacles) + "]"
    seen_pl = "\n".join(f'pick_and_place("{x[0]}", "{x[1]}")' for x in sc.seen_placements)
    unseen = "[" + ", ".join(f'"{x}"' for x in objects) + "]"
    return (
        f"objects = {seen}\nreceptacles = {recep}\n{seen_pl}\n    \n"
        f"objects = {unseen}\nreceptacles = {recep}\npick_and_place(\"{objects[0]}\","
    )


SUMM_TEMPLATE = '''objects = ["dried figs", "protein bar", "cornmeal", "Macadamia nuts", "vinegar", "herbal tea", "peanut oil", "chocolate bar", "bread crumbs", "Folgers instant coffee"]
receptacles = ["top rack", "middle rack", "table", "shelf", "plastic box"]
pick_and_place("dried figs", "plastic box")
pick_and_place("protein bar", "shelf")
pick_and_place("cornmeal", "top rack")
pick_and_place("Macadamia nuts", "plastic box")
pick_and_place("vinegar", "middle rack")
pick_and_place("herbal tea", "table")
pick_and_place("peanut oil", "middle rack")
pick_and_place("chocolate bar", "shelf")
pick_and_place("bread crumbs", "top rack")
pick_and_place("Folgers instant coffee", "table")
# Summary: Put dry ingredients on the top rack, liquid ingredients in the middle rack, tea and coffee on the table, packaged snacks on the shelf, and dried fruits and nuts in the plastic box.

objects = ["yoga pants", "wool sweater", "black jeans", "Nike shorts"]
receptacles = ["hamper", "bed"]
pick_and_place("yoga pants", "hamper")
pick_and_place("wool sweater", "bed")
pick_and_place("black jeans", "bed")
pick_and_place("Nike shorts", "hamper")
# Summary: Put athletic clothes in the hamper and other clothes on the bed.

objects = ["Nike sweatpants", "sweater", "cargo shorts", "iPhone", "dictionary", "tablet", "Under Armour t-shirt", "physics homework"]
receptacles = ["backpack", "closet", "desk", "nightstand"]
pick_and_place("Nike sweatpants", "backpack")
pick_and_place("sweater", "closet")
pick_and_place("cargo shorts", "closet")
pick_and_place("iPhone", "nightstand")
pick_and_place("dictionary", "desk")
pick_and_place("tablet", "nightstand")
pick_and_place("Under Armour t-shirt", "backpack")
pick_and_place("physics homework", "desk")
# Summary: Put workout clothes in the backpack, other clothes in the closet, books and homeworks on the desk, and electronics on the nightstand.

objects = {objects}
receptacles = {receptacles}
{placements}
# Summary:'''


def prompt_summarize(sc):
    objs = "[" + ", ".join(f'"{x}"' for x in sc.seen_objects) + "]"
    recep = "[" + ", ".join(f'"{x}"' for x in sc.receptacles) + "]"
    pl = "\n".join(f'pick_and_place("{x[0]}", "{x[1]}")' for x in sc.seen_placements)
    return SUMM_TEMPLATE.format(objects=objs, receptacles=recep, placements=pl)


def prompt_placement_with_summary(summary, objects, receptacles):
    objs = "[" + ", ".join(f'"{x}"' for x in objects) + "]"
    recep = "[" + ", ".join(f'"{x}"' for x in receptacles) + "]"
    return (
        '# Summary: Put clothes in the laundry basket and toys in the storage box.\n'
        'objects = ["socks", "toy car", "shirt", "Lego brick"]\n'
        'receptacles = ["laundry basket", "storage box"]\n'
        'pick_and_place("socks", "laundry basket")\n'
        'pick_and_place("toy car", "storage box")\n'
        'pick_and_place("shirt", "laundry basket")\n'
        'pick_and_place("Lego brick", "storage box")\n\n'
        f"# Summary: {summary}\nobjects = {objs}\nreceptacles = {recep}\n"
        f'pick_and_place("{objects[0]}",'
    )


def run_examples_only(scenarios, llm):
    accs, rows = [], []
    for i, sc in enumerate(scenarios):
        out = llm.gen(placements_examples_only(sc, sc.unseen_objects))
        pred = benchmark.parse_placements(out, sc.unseen_objects)
        _, acc = benchmark.check_placements(pred, sc.unseen_placements)
        accs.append(acc); rows.append([i, round(acc, 2), "|".join(f"{o}->{r}" for o, r in pred)])
        print(f"  [examples_only] {i+1}/{len(scenarios)} acc={acc:.2f}")
    return accs, rows


def run_summarization(scenarios, llm):
    accs, rows = [], []
    for i, sc in enumerate(scenarios):
        summ = benchmark.parse_summary(llm.gen(prompt_summarize(sc)))
        out = llm.gen(prompt_placement_with_summary(summ, sc.unseen_objects, sc.receptacles))
        pred = benchmark.parse_placements(out, sc.unseen_objects)
        _, acc = benchmark.check_placements(pred, sc.unseen_placements)
        accs.append(acc); rows.append([i, round(acc, 2), summ, "|".join(f"{o}->{r}" for o, r in pred)])
        print(f"  [summarization] {i+1}/{len(scenarios)} acc={acc:.2f}")
    return accs, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--model-path", default=os.path.join(HERE, "models", "qwen2.5-3b"))
    args = ap.parse_args()

    scenarios = benchmark.load_scenarios(os.path.join(BENCH_DIR, "scenarios.yml"))[: args.n]
    print(f"TidyBot 基准: 前 {len(scenarios)} 个场景, 本地模型: {args.model_path}")
    llm = LocalLLM(args.model_path)

    t0 = time.time()
    acc_ex, rows_ex = run_examples_only(scenarios, llm)
    acc_sm, rows_sm = run_summarization(scenarios, llm)
    elapsed = time.time() - t0

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", f"tidybot_examples_only{tag}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scenario", "accuracy", "predictions"]); w.writerows(rows_ex)
    with open(os.path.join(HERE, "results", f"tidybot_summarization{tag}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scenario", "accuracy", "summary", "predictions"]); w.writerows(rows_sm)

    summary = {
        "feature": "F3", "benchmark": "TidyBot preference (first %d scenarios)" % len(scenarios),
        "model": os.path.basename(args.model_path), "provider": "local transformers (paper used OpenAI Completion)",
        "examples_only_acc": round(100 * sum(acc_ex) / len(acc_ex), 1),
        "summarization_acc": round(100 * sum(acc_sm) / len(acc_sm), 1),
        "paper": {"examples_only": 78.5, "summarization": 91.2},
        "n_scenarios": len(scenarios), "elapsed_sec": round(elapsed, 1),
    }
    tag = "" if args.n == 20 else f"_{args.n}"
    json.dump(summary, open(os.path.join(HERE, "results", f"tidybot_f3{tag}.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"\n===== F3 结果（{len(scenarios)} 个场景）=====")
    print(f"只看示例     : {summary['examples_only_acc']}%  (论文 78.5%)")
    print(f"先归纳再推断 : {summary['summarization_acc']}%  (论文 91.2%)")


if __name__ == "__main__":
    main()

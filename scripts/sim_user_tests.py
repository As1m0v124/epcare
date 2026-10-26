#!/usr/bin/env python3
"""模拟用户测试（replay 模式，第 1 轮）：3 角色 × 5 任务，记录完成率/步骤数/耗时/出错点。

用法: ai312/bin/python scripts/sim_user_tests.py
输出: results/sim_user_tests.json + docs/sim_user_results.md
"""
import json
import os
import time

import requests

BASE = os.environ.get("EPCARE_API", "http://127.0.0.1:8000")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def login(user, pwd):
    s = requests.Session()
    s.post(BASE + "/api/login", json={"username": user, "password": pwd}, timeout=10).raise_for_status()
    return s


def run_checks():
    """返回 [(角色, 任务, 结果列表[(步骤名, 是否成功, 备注)])]"""
    admin = login("admin", "admin123")
    care = login("caregiver1", "care123")
    fam = login("family1", "family123")
    out = []

    def case(role, name, fn):
        steps, t0 = [], time.time()
        try:
            fn(steps)
            ok = all(s[1] for s in steps)
        except Exception as e:
            ok = False
            steps.append((f"异常 {e!r}", False, ""))
        out.append({"role": role, "task": name, "ok": ok,
                    "steps": len(steps), "elapsed": round(time.time() - t0, 1),
                    "detail": [{"step": s[0], "ok": s[1], "note": s[2]} for s in steps]})

    # ---------- 家属 ----------
    def a1(steps):
        r = fam.post(BASE + "/api/tasks/find", json={"query": "老花镜"}, timeout=120)
        d = r.json(); steps.append(("找东西接口", r.ok, f"{d.get('count')} 个"))
        steps.append(("返回截图", "shot" in json.loads(fam.get(f"{BASE}/api/tasks/{d['task_id']}").json()["result"]) if r.ok else False, ""))
    case("family", "A1 找奶奶的老花镜", a1)

    def a2(steps):
        r = fam.get(BASE + "/api/dashboard"); steps.append(("打开看板", r.ok, f"HTTP {r.status_code}"))
        d = r.json(); steps.append(("包含任务统计", "tasks" in d, str(d.get("tasks"))))
    case("family", "A2 查看今日巡检统计", a2)

    def a3(steps):
        r = fam.post(BASE + "/api/rules", json={"examples": ["白袜子:脏衣篮", "降压药:床头柜", "遥控器:茶几", "拖鞋:门口"]}, timeout=300)
        d = r.json(); steps.append(("归纳规则", r.ok, d.get("model", "")))
        steps.append(("规则非空", bool(d.get("rules")), ""))
    case("family", "A3 录入示例并归纳", a3)

    def a4(steps):
        r1 = fam.post(BASE + "/api/rules", json={"examples": ["白袜子:脏衣篮", "拖鞋:门口"]}, timeout=300).json()
        r2 = fam.post(BASE + "/api/rules", json={"examples": ["白袜子:洗衣篮", "拖鞋:鞋柜"]}, timeout=300).json()
        steps.append(("两次归纳", bool(r1.get("rules")) and bool(r2.get("rules")), ""))
        steps.append(("纠正后变化", r1.get("rules") != r2.get("rules"), ""))
    case("family", "A4 纠正归纳结果", a4)

    def a5(steps):
        r = fam.get(BASE + "/api/assistant", params={"q": "去卧室找一下遥控器，先别捡，拍张照"})
        d = r.json(); steps.append(("助手路由", r.ok, d.get("action", "")))
        steps.append(("识别为找东西", d.get("action") == "find", d.get("query", "")))
    case("family", "A5 助手转找东西", a5)

    # ---------- 护理员 ----------
    def b1(steps):
        rooms = care.get(BASE + "/api/rooms").json()
        for r in rooms:
            if not r["landmarks"]:
                admin.post(BASE + f"/api/rooms/{r['id']}/landmarks",
                           json={"name": "床头", "tag_id": "TAG-BED"})
        rooms = care.get(BASE + "/api/rooms").json()
        target = [r for r in rooms if r["landmarks"]][:3]
        ok = 0
        for r in target:
            d = care.post(BASE + "/api/tasks/patrol", json={"room_id": r["id"]}, timeout=20).json()
            ok += bool(d.get("plan"))
        steps.append(("3 个房间生成计划", ok == min(3, len(target)), f"{ok}/{len(target)} 个成功"))
    case("caregiver", "B1 三个房间排巡检", b1)

    def b2(steps):
        a = care.post(BASE + "/api/alerts", json={"room_id": 1, "kind": "cable", "description": "地上有电线"}).json()
        steps.append(("生成告警", bool(a.get("id")), f"#{a.get('id')}"))
        r = care.post(BASE + f"/api/alerts/{a['id']}/resolve"); steps.append(("标记已处理", r.ok, ""))
    case("caregiver", "B2 处理电线告警", b2)

    def b3(steps):
        r = care.get(BASE + "/api/tasks"); steps.append(("任务列表", r.ok and isinstance(r.json(), list), f"{len(r.json())} 条"))
    case("caregiver", "B3 查看历史任务", b3)

    def b4(steps):
        a = care.post(BASE + "/api/alerts", json={"room_id": 1, "kind": "fragile", "description": "发现玻璃杯"}).json()
        steps.append(("易碎品告警", bool(a.get("id")), a.get("photo", "无照片")))
    case("caregiver", "B4 易碎品转告警", b4)

    def b5(steps):
        r1 = care.post(BASE + "/api/control/estop"); steps.append(("护理员急停", r1.ok, ""))
        r2 = care.post(BASE + "/api/control/move", json={"x": 0.2}); steps.append(("移动被拒", r2.status_code == 423, f"HTTP {r2.status_code}"))
        admin.post(BASE + "/api/control/clear-estop")
    case("caregiver", "B5 急停可用", b5)

    # ---------- 管理员 ----------
    def c1(steps):
        r = admin.post(BASE + "/api/rooms", json={"name": "厨房", "note": "模拟居家"})
        rid = r.json().get("id")
        steps.append(("新增房间", r.ok or r.status_code == 400, f"HTTP {r.status_code}"))
        rooms = admin.get(BASE + "/api/rooms").json()
        target = rid or rooms[-1]["id"]
        rr = admin.post(BASE + f"/api/rooms/{target}/landmarks", json={"name": "冰箱", "tag_id": "TAG-FRIDGE"})
        steps.append(("新增地标", rr.ok, ""))
    case("admin", "C1 新增房间与地标", c1)

    def c2(steps):
        r = admin.post(BASE + "/api/control/limits", json={"speed_limit": 0.5, "max_move": 0.8, "arm_limit_mm": 50})
        steps.append(("修改参数", r.ok, json.dumps(r.json(), ensure_ascii=False)))
        st = admin.get(BASE + "/api/control/state").json()
        steps.append(("参数生效", st.get("speed_limit") == 0.5 and st.get("arm_limit_mm") == 50, ""))
        admin.post(BASE + "/api/control/limits", json={"speed_limit": 0.6, "max_move": 1.0, "arm_limit_mm": 60})
    case("admin", "C2 修改限速与限幅", c2)

    def c3(steps):
        r = admin.post(BASE + "/api/control/connect", json={"mode": "replay"}); steps.append(("连接回放", r.ok, ""))
        st = admin.get(BASE + "/api/control/state").json()
        steps.append(("状态正确", st.get("connected") and st.get("mode") == "replay", str(st.get("mode"))))
    case("admin", "C3 连接并查看状态", c3)

    def c4(steps):
        r = admin.get(BASE + "/api/audit"); d = r.json()
        steps.append(("审计可读", r.ok and len(d.get("backend", [])) > 0, f"{len(d.get('backend', []))} 条"))
    case("admin", "C4 查看审计日志", c4)

    def c5(steps):
        admin.post(BASE + "/api/control/estop")
        r = admin.post(BASE + "/api/control/clear-estop"); steps.append(("急停并解除", r.ok and not r.json().get("estop"), ""))
    case("admin", "C5 触发并解除急停", c5)

    return out


def main():
    results = run_checks()
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    summary = {"mode": "replay", "total": total, "passed": passed,
               "pass_rate": round(100 * passed / total, 1),
               "avg_steps": round(sum(r["steps"] for r in results) / total, 1),
               "avg_elapsed_sec": round(sum(r["elapsed"] for r in results) / total, 1),
               "cases": results}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(summary, open(os.path.join(HERE, "results", "sim_user_tests.json"), "w"),
              ensure_ascii=False, indent=2)

    lines = [f"# 模拟用户测试结果（第 1 轮 · replay 模式）", "",
             f"- 通过率：**{summary['pass_rate']}%**（{passed}/{total}）",
             f"- 平均步骤数：{summary['avg_steps']}；平均耗时：{summary['avg_elapsed_sec']}s", "",
             "| 角色 | 任务 | 结果 | 步骤 | 耗时(s) | 出错点 |", "|---|---|---|---|---|---|"]
    for r in results:
        errs = [d["step"] for d in r["detail"] if not d["ok"]]
        lines.append(f"| {r['role']} | {r['task']} | {'✅' if r['ok'] else '❌'} | {r['steps']} | {r['elapsed']} | {'；'.join(errs) or '—'} |")
    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    open(os.path.join(HERE, "docs", "sim_user_results.md"), "w").write("\n".join(lines) + "\n")
    print(f"通过率 {summary['pass_rate']}% ({passed}/{total})，平均 {summary['avg_steps']} 步 / {summary['avg_elapsed_sec']}s")
    for r in results:
        print(("✅" if r["ok"] else "❌"), r["role"], r["task"], f"{r['elapsed']}s")


if __name__ == "__main__":
    main()

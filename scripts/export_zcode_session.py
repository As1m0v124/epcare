#!/usr/bin/env python3
"""导出 ZCode 某个会话为项目可提交的 Markdown。

从 ~/.zcode/cli/db/db.sqlite 按 session_id 读取 message/part：
- 保留：用户文字/附件名、助手可见文字、工具调用名与参数、工具报错；
- 剔除：reasoning、system/记忆、step/timeline、普通工具输出、其它会话；
- 自动脱敏 token、把家目录替换为 ~。

用法:
  ai312/bin/python scripts/export_zcode_session.py \
    --session-id sess_87ed69ab-f6fb-4b1c-abaa-4bdcbeb6bce8 \
    --out-dir agent-sessions/2026-11-09 --date 2026-11-09
"""
import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import date

HOME = os.path.expanduser("~")
DEFAULT_DB = os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite")


def redact(s):
    s = str(s).replace(HOME, "~")
    s = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]", s)
    s = re.sub(r"ghp_[A-Za-z0-9]{20,}", "[REDACTED_GITHUB_TOKEN]", s)
    s = re.sub(r"github_pat_[A-Za-z0-9_]{20,}", "[REDACTED_GITHUB_TOKEN]", s)
    s = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", s)
    s = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]{10,}", r"\1[REDACTED]", s)
    return s


def clean_user(s):
    s = s.strip()
    if "<in-app-browser-context" in s and "## My request for ZCode:" in s:
        s = s.split("## My request for ZCode:", 1)[1].strip()
    return s


def load_session(session_id, db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    s = con.execute("select * from session where id=?", (session_id,)).fetchone()
    if not s:
        raise SystemExit(f"数据库里没有会话 {session_id}")
    rows = con.execute("""
        select m.id mid, m.sequence mseq, m.data mdata,
               p.sequence pseq, p.data pdata
        from message m left join part p on p.message_id=m.id
        where m.session_id=? order by m.sequence, p.sequence
    """, (session_id,)).fetchall()
    groups = {}
    for r in rows:
        g = groups.setdefault(r["mid"], {"mseq": r["mseq"], "mdata": json.loads(r["mdata"]), "parts": []})
        if r["pdata"] is not None:
            g["parts"].append(json.loads(r["pdata"]))
    return dict(s), [groups[k] for k in sorted(groups, key=lambda x: groups[x]["mseq"])]


def tool_line(p):
    name = p.get("tool", "tool")
    st = p.get("state") or {}
    inp = st.get("input") or {}
    raw = json.dumps(inp, ensure_ascii=False).replace("`", "'")
    if len(raw) > 260:
        raw = raw[:260] + " …"
    status = st.get("status")
    if status in ("error", "failed") or st.get("error"):
        out = st.get("error") or st.get("output") or ""
        out = redact(str(out))[:700].replace("\n", " ")
        return f"> 工具错误 `{name}`：{out}\n"
    return f"> 工具 `{name}`：`{redact(raw)}`\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--title", default="epcare")
    ap.add_argument("--date", default=date.today().isoformat())
    args = ap.parse_args()
    if not re.match(r"^sess_[A-Za-z0-9._-]+$", args.session_id):
        raise SystemExit("session id 格式不对")
    sess, msgs = load_session(args.session_id, args.db)
    # 截止到老师提出“第四样提交物”之前，避免把导出工具自身的对话也写进去
    cut_seq = None
    for g in msgs:
        if g["mdata"].get("role") != "user":
            continue
        txt = "\n".join(p.get("text", "") for p in g["parts"] if p.get("type") == "text")
        if "第四样提交物品从下周周交付起" in txt:
            cut_seq = g["mseq"]
            break
    if cut_seq is not None:
        msgs = [g for g in msgs if g["mseq"] < cut_seq]
    out_dir = args.out_dir or os.path.join("agent-sessions", args.date)
    os.makedirs(out_dir, exist_ok=True)

    lines = [f"# {args.title} · ZCode 对话记录（{args.date}）", "",
             f"- 会话 ID：`{args.session_id}`",
             f"- 会话标题：{sess.get('title', '')}",
             f"- 工作目录：{sess.get('directory', '').replace(HOME, '~')}",
             "- 范围：仅本 302 毕设项目；已剔除 reasoning、系统提示、memory、step/timeline、普通工具输出与其它会话。",
             "- 说明：由 `scripts/export_zcode_session.py` 从 ZCode 本地 SQLite 会话导出。", ""]
    n_user = n_asst = n_tool = n_err = 0
    for g in msgs:
        role = g["mdata"].get("role")
        texts, files, tools = [], [], []
        for p in g["parts"]:
            t = p.get("type")
            if t == "text":
                texts.append(p.get("text", ""))
            elif t == "file":
                files.append(p.get("filename") or p.get("url", ""))
            elif t == "tool":
                tools.append(p)
        body = "\n".join(x for x in texts if x).strip()
        if role == "user":
            body = clean_user(body)
            if not body and not files:
                continue
            head = body.lstrip()
            injected = (
                head.startswith("<system-reminder")
                or head.startswith("<task-notification")
                or head.startswith("[SYSTEM NOTIFICATION")
                or head.startswith("Called the Read tool")
                or head.startswith("Called the ")
                or head.startswith("This session is being continued")
                or head.startswith("The TodoWrite tool hasn't been used recently")
                or "Result of the " in head[:120]
                or "# Memory Index" in head
                or head.startswith("# agentsMd")
            )
            if injected:
                continue
            n_user += 1
            lines += ["## 用户", "", redact(body)]
            for f in files:
                lines += ["", f"> 附件：`{redact(f)}`"]
            lines += [""]
        elif role == "assistant":
            if body:
                n_asst += 1
                lines += ["## 助手", "", redact(body), ""]
            for p in tools:
                raw = json.dumps((p.get("state") or {}).get("input") or {}, ensure_ascii=False)
                if ".zcode/cli/memories" in raw or "MEMORY.md" in raw or "agent-sessions" in raw:
                    continue  # 不导出记忆/导出工具自身的操作
                n_tool += 1
                if (p.get("state") or {}).get("status") in ("error", "failed") or (p.get("state") or {}).get("error"):
                    n_err += 1
                lines += [tool_line(p)]
            if tools and (not body or lines[-1] != ""):
                lines += [""]

    out = os.path.join(out_dir, f"zcode-{args.title}-{args.date}.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines).rstrip() + "\n")
    meta = {"session_id": args.session_id, "title": sess.get("title"), "date": args.date,
            "directory": sess.get("directory"), "source": args.db,
            "messages": len(msgs), "user_turns": n_user, "assistant_texts": n_asst,
            "tool_calls": n_tool, "tool_errors": n_err,
            "excluded": ["reasoning", "system", "memory", "step", "timeline", "tool outputs (non-error)"]}
    json.dump(meta, open(os.path.join(out_dir, "session-metadata.json"), "w"), ensure_ascii=False, indent=2)
    readme = f"""# agent-sessions / {args.date}

本目录是 302 毕设项目在 ZCode 里的对话导出，用于老师分析编程方法、提示词写法与 bug。

- 会话：`{args.session_id}`（{sess.get('title','')}）
- 导出：`scripts/export_zcode_session.py`，来自 ZCode 本地 SQLite 会话
- 范围：仅本项目；不含其它课程/私人项目、reasoning、系统提示、memory、普通工具输出
- 统计：用户 {n_user} 条、助手文本 {n_asst} 条、工具调用 {n_tool} 次（报错 {n_err} 次）

如需复核，运行同一脚本并指定同一 session id 即可重新生成。
"""
    open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8").write(readme)
    print(f"导出 {out}（{os.path.getsize(out)/1024:.0f} KB）")
    print(f"用户 {n_user}、助手文本 {n_asst}、工具调用 {n_tool}、工具报错 {n_err}")


if __name__ == "__main__":
    main()

# Agent 对话记录（302 项目）

按老师要求，从 2026-11-09 起按周导出本项目在 AI 编程工具里的对话，供分析编程方法、提示词写法和 bug。

- 目录：`agent-sessions/YYYY-MM-DD/`
- 只包含 **本 302 毕设项目** 的会话；不含其它课程、私人项目、系统提示、memory、reasoning、普通工具输出；
- ZCode 导出脚本：`scripts/export_zcode_session.py`（读 `~/.zcode/cli/db/db.sqlite` 的指定 session）；
- 其它工具（Cursor / Claude Code / Codex）请用各自导出功能，同样只导本项目，放到对应日期目录；
- 大文件（视频、模型权重）不入库。

示例：

```bash
ai312/bin/python scripts/export_zcode_session.py \
  --session-id sess_xxxxxxxx --out-dir agent-sessions/2026-11-16 --date 2026-11-16
```

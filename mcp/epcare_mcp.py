#!/usr/bin/env python3
"""EPCare MCP Server（stdio JSON-RPC，无第三方依赖）。

提供工具：
  epcare_status      查询机器人与任务状态
  epcare_find        用中文描述找东西（返回框/分数/距离）
  epcare_depth       对本地图片生成深度图（保存 PNG）
  epcare_patrol_plan 生成巡检计划（可选 replay 演练）
  epcare_tidy_rules  归纳收纳规则（示例行：物品:位置）

启动（ai312 环境）: ai312/bin/python mcp/epcare_mcp.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = os.environ.get("EPCARE_API", "http://127.0.0.1:8000")
USER = os.environ.get("EPCARE_USER", "admin")
PWD = os.environ.get("EPCARE_PASS", "admin123")

TOOLS = [
    {"name": "epcare_status", "description": "查询机器人连接状态与安全参数",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "epcare_find", "description": "用中文描述在实时画面里找东西",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                     "required": ["query"]}},
    {"name": "epcare_depth", "description": "对本地图片生成深度图 PNG",
     "inputSchema": {"type": "object", "properties": {"image": {"type": "string"},
                                                     "out": {"type": "string"}},
                     "required": ["image"]}},
    {"name": "epcare_patrol_plan", "description": "生成房间巡检计划（按地标最近邻）",
     "inputSchema": {"type": "object", "properties": {"room": {"type": "string"},
                                                     "rehearse": {"type": "boolean"}},
                     "required": ["room"]}},
    {"name": "epcare_tidy_rules", "description": "从示例行归纳收纳规则",
     "inputSchema": {"type": "object", "properties": {"examples": {"type": "array",
                                                                  "items": {"type": "string"}}},
                     "required": ["examples"]}},
]


def client():
    import requests
    s = requests.Session()
    r = s.post(BASE + "/api/login", json={"username": USER, "password": PWD}, timeout=10)
    r.raise_for_status()
    return s


def call_tool(name, args):
    if name == "epcare_depth":
        from backend import ml
        data = open(args["image"], "rb").read()
        png, depth = ml.depth_map(data)
        out = args.get("out", "depth.png")
        open(out, "wb").write(png)
        return {"content": [{"type": "text", "text": f"深度图已保存 {out}（越大越近）"}]}

    s = client()
    if name == "epcare_status":
        d = s.get(BASE + "/api/control/state", timeout=10).json()
    elif name == "epcare_find":
        d = s.post(BASE + "/api/tasks/find", json={"query": args["query"]}, timeout=120).json()
    elif name == "epcare_patrol_plan":
        rooms = s.get(BASE + "/api/rooms", timeout=10).json()
        match = [r for r in rooms if r["name"] == args["room"] or str(r["id"]) == args["room"]]
        if not match:
            return {"content": [{"type": "text", "text": "房间不存在"}], "isError": True}
        d = s.post(BASE + "/api/tasks/patrol",
                   json={"room_id": match[0]["id"], "rehearse": bool(args.get("rehearse"))},
                   timeout=20).json()
    elif name == "epcare_tidy_rules":
        d = s.post(BASE + "/api/rules", json={"examples": args["examples"]}, timeout=300).json()
    else:
        return {"content": [{"type": "text", "text": f"未知工具 {name}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(d, ensure_ascii=False, indent=1)}]}


def respond(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error:
        out["error"] = {"code": error[0], "message": error[1]}
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            respond(mid, {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "epcare", "version": "0.1.0"}})
        elif method in ("notifications/initialized",):
            continue
        elif method == "tools/list":
            respond(mid, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                respond(mid, call_tool(name, args))
            except Exception as e:
                respond(mid, error=(-32000, repr(e)))
        elif method == "ping":
            respond(mid, {})
        else:
            respond(mid, error=(-32601, f"method not found: {method}"))


if __name__ == "__main__":
    main()

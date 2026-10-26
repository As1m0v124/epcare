#!/bin/bash
# EPCare 一键启动：控制服务(:8001) + 后端(:8000) + 打开浏览器
# 用法: bash start.sh [replay|real]
# 说明: replay = 回放历史实拍帧（开发/演示，不动真机）；real = 连接真机（STA 组网）
set -e
cd "$(dirname "$0")"
MODE="${1:-replay}"
mkdir -p logs

echo "==> 启动控制服务 (:8001)"
( ep38/bin/python -m uvicorn services.control.server:app --host 127.0.0.1 --port 8001 \
    > logs/control.log 2>&1 & echo $! > logs/control.pid )

echo "==> 启动后端 (:8000)"
( ai312/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 \
    > logs/backend.log 2>&1 & echo $! > logs/backend.pid )

sleep 3
echo "==> 连接机器人模式: $MODE"
curl -s -X POST http://127.0.0.1:8000/api/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' -c /tmp/epcare.cookie > /dev/null
curl -s -b /tmp/epcare.cookie -X POST http://127.0.0.1:8001/connect \
  -H 'Content-Type: application/json' -d "{\"mode\":\"$MODE\"}" || true

open http://127.0.0.1:8000 2>/dev/null || true
echo "已启动：http://127.0.0.1:8000 （admin/admin123）"
echo "停止: kill \$(cat logs/control.pid) \$(cat logs/backend.pid)"

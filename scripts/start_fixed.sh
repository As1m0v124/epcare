#!/bin/bash
# 修复版：启动控制服务+后端，等待机器人上线并自动连接，然后打开网页客户端。
# 用法: bash scripts/start_fixed.sh
set -e
cd "$(dirname "$0")/.."
export EP_IP="${EP_IP:-10.197.63.238}"

echo "==> 启动修复版（有界队列，不会指令堆积）"
bash start.sh real
ai312/bin/python scripts/connect_robot.py --ip "$EP_IP" --timeout 120 || true

echo "==> 连接状态:"
curl -s http://127.0.0.1:8001/state; echo
open "http://127.0.0.1:8000" 2>/dev/null || true
echo "✅ 修复版已就绪：浏览器里 admin/admin123 登录，可自由控制小车/机械臂（队列满会提示忙，等 1 秒再按）"

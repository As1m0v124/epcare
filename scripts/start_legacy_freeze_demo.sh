#!/bin/bash
# 旧版卡死演示：以 EPCARE_LEGACY=1 启动（直接并发调 SDK，无队列），自动连机器人并打开网页。
# 用法:
#   bash scripts/start_legacy_freeze_demo.sh            # 只启动旧版，手动操作
#   bash scripts/start_legacy_freeze_demo.sh --run-demo # 自动跑 36 条并发并生成“卡死”标注图
#   DEMO_ACT=move bash scripts/start_legacy_freeze_demo.sh --run-demo  # 用移动小车演示
set -e
cd "$(dirname "$0")/.."
export EP_IP="${EP_IP:-10.197.63.238}"
export EPCARE_LEGACY=1

echo "==> 启动旧版（无队列，指令会无限堆积）"
bash start.sh real
ai312/bin/python scripts/connect_robot.py --ip "$EP_IP" --timeout 120
echo "⚠️ 旧版已连接：连续操作后会卡死；这是演示用，正常使用请跑 scripts/start_fixed.sh"

if [ "$1" = "--run-demo" ]; then
  echo
  echo "准备好录屏后，按回车开始 36 条并发卡死演示（会移动机械臂，周围清空）..."
  read -r
  ai312/bin/python scripts/repro_pileup.py --n 36 --tag before --annotate --act "${DEMO_ACT:-arm}"
  echo
  echo "演示结束：标注图在 results/pileup_before_annotated.jpg；旧版只能重启服务恢复。"
fi

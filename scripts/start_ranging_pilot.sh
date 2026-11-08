#!/bin/bash
# 10 张测距 pilot：机器人不动，物体沿砖缝摆；距离用砖数（1t=0.6m）
cd "$(dirname "$0")/.."
echo "=============================================="
echo " 测距 pilot：10 张（瓷砖 / 白天，机器人不动）"
echo " 1-4  水瓶：1t / 2t / 3t / 4t"
echo " 5-7  盒子：1t / 2t / 3t"
echo " 8-10 收纳包：1t / 2t / 3t"
echo " 拍完点物体最底部贴地点；输入如 水瓶:2t"
echo "=============================================="
exec ai312/bin/python -u scripts/collect_ranging_data.py \
  --out data/ep_ranging --n 10 --tile-m 0.6 \
  --camera-height 0.25 --camera-pitch 0 \
  --surface 瓷砖 --light 白天

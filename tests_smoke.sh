#!/bin/bash
# 系统冒烟测试：需先 bash start.sh replay
set -e
B=http://127.0.0.1:8000
C=/tmp/epcare_smoke.cookie
curl -sf -c $C -X POST $B/api/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' > /dev/null
curl -sf -b $C -X POST $B/api/control/connect -H 'Content-Type: application/json' -d '{"mode":"replay"}' > /dev/null
curl -sf -b $C $B/api/control/state | grep -q '"connected":true'
curl -sf -b $C $B/api/control/frame.jpg -o /tmp/smoke.jpg
curl -sf -b $C $B/api/depth.jpg -o /tmp/smoke_depth.png
curl -sf -b $C -X POST $B/api/detect -H 'Content-Type: application/json' -d '{"query":"水瓶"}' | grep -q '"count"'
curl -sf -b $C -X POST $B/api/tasks/find -H 'Content-Type: application/json' -d '{"query":"水瓶"}' | grep -q task_id
curl -sf -b $C -X POST $B/api/tasks/patrol -H 'Content-Type: application/json' -d '{"room_id":1,"rehearse":true}' | grep -q plan
curl -sf -b $C -X POST $B/api/rules -H 'Content-Type: application/json' -d '{"examples":["袜子:脏衣篮","药:床头柜"]}' | grep -q rules
curl -sf -b $C $B/api/eval | grep -q F1
echo "✅ 冒烟测试通过"

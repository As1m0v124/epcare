# 巡检一圈录屏操作单（11/10 验收用）

> 目标：从机器人开机开始，完整录到“跑完一圈 + 4 个角照片”，中间不剪掉关键失败步骤。
> 适用：EP 已修好、Mac 与机器人同一 Wi-Fi（sta 组网），机器人 IP 见 `EP_IP`。

## 0. 录屏前检查（2 分钟）

- [ ] 机器人电量 >80%（网页驾驶舱可看；低于 25% 服务会拒动）；
- [ ] 场地 ≥1.5m×1.5m 空旷，地面无电线/宠物/人脚；
- [ ] Mac 已连机器人所在 Wi-Fi，`ping -c 3 10.197.63.238` 通；
- [ ] 手机/相机对着电脑屏幕开始录（或 Mac 自带录屏），**从机器人开机画面开始录**；
- [ ] 录屏中不要暂停、不要跳剪；某一步失败就当场说明“这一步失败了，原因是…”，再继续。

## 1. 开机 + 启动服务（录进画面）

```bash
# 终端 1：确认机器人上线（开机后约 20–40 秒）
ping -c 3 10.197.63.238

# 启动控制服务(:8001) + 后端(:8000) + 浏览器
cd ~/ep-project
bash start.sh real
```

浏览器打开 `http://127.0.0.1:8000`，`admin / admin123` 登录。

**视频要求：在终端执行并展示本周提交哈希**

```bash
cd ~/ep-project && git log -1 --oneline
```

## 2. 驾驶舱自检（约 30 秒）

- [ ] 实时画面在动（MJPEG ~15fps），不是黑屏/最后一帧；
- [ ] 点“深度图”能出彩色深度；
- [ ] 输入“水杯”能出检测框（有就展示，没有说明“当前画面没有该类物体”，不算失败）；
- [ ] 按一下急停，确认所有动作被拒（423），再解除。

## 3. 真机巡检一圈（主录屏内容）

1. 左侧进入 **巡检任务** 页；
2. “真机巡检一圈”里把每边设为 `0.3` 米；
3. 点 **跑真机一圈（4 边 + 4 个 90°）**；
4. 弹出确认框后，镜头转向机器人，确认它开始前进 → 右转 → 前进 → …；
5. 页面会列出 8 个步骤（4 次前进 + 4 次右转）和 4 张角落照片；
6. 结束后展示任务状态 `finished` 和 4 张照片，再回驾驶舱确认画面仍在。

**失败也要录**：如果出现 429（队列忙）、急停、画面卡住、转弯角度不足、照片黑屏等，
当场说明现象 → 原因 → 处理（例如“这是排队保护，等 1 秒再按”），不要剪掉。

> 机器人走完 4 边会回到起点附近，方向转满 360°；若地面打滑导致角度偏差，属真实误差，如实说明。

## 4. 收尾

- 回驾驶舱按 **急停**（演示急停有效），或让机器人停止；
- 展示 `results/patrol/loop_<任务号>_*.jpg` 4 张照片和任务历史；
- 结束录屏。

## 5. 附：卡死复现/修复对比录屏（可与巡检录屏分开）

```bash
# A. 旧版：复现卡死（36 条并发，第 37 条 10 秒超时）
pkill -9 -f services.control.server
EPCARE_LEGACY=1 EP_IP=10.197.63.238 nohup ep38/bin/python -m uvicorn \
  services.control.server:app --host 127.0.0.1 --port 8001 > logs/control_legacy.log 2>&1 &
sleep 4
curl -s -X POST http://127.0.0.1:8001/connect -H 'Content-Type: application/json' -d '{"mode":"real"}'
ai312/bin/python scripts/repro_pileup.py --n 36 --tag before
# 预期：批量 36×200，p50≈7.5s，探测指令 10s 超时 → frozen:true

# B. 修复版：同样的 36 条，多余请求立即 429，第 37 条 0.4 秒返回
pkill -9 -f services.control.server
EP_IP=10.197.63.238 nohup ep38/bin/python -m uvicorn \
  services.control.server:app --host 127.0.0.1 --port 8001 > logs/control.log 2>&1 &
sleep 4
curl -s -X POST http://127.0.0.1:8001/connect -H 'Content-Type: application/json' -d '{"mode":"real"}'
ai312/bin/python scripts/repro_pileup.py --n 36 --tag after
# 预期：3×200 + 33×429，探测指令 <1s 返回 200 → frozen:false
```

> 旧版跑完后队列里还有动作，直接 Ctrl-C/杀进程就是“只能重启”的真实演示；重启后等 2 秒再连。

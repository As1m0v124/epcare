# 11/10 实验室一次 session 执行单

> 目标：一次做完 ①完整巡检录屏（从开机）②卡死前后对比录屏 ③20 张测距 pilot。
> 顺序很重要：巡检必须从机器人开机开始录，所以先做 A；卡死对比要重启服务，放 B；测距放最后 C。

## 0. 出发前（5 分钟）

- [ ] 机器人电量 >80%，带卷尺（或确认地砖 600mm）；
- [ ] 场地 1.5m×1.5m 空旷，地面无电线；
- [ ] 手机/录屏软件就绪，确认能录到终端和网页；
- [ ] 3–5 个轻物体（水瓶、盒子、拖鞋、收纳包），高度 5–30cm；
- [ ] 当前提交：`cd ~/ep-project && git log --oneline -1`（视频里要出现）。

## A. 完整巡检录屏（先录，约 8 分钟）

1. 关掉机器人电源；**开始录屏**（画面里要有机器人关机状态）；
2. 机器人开机，等 20–40 秒；终端 `ping -c 3 10.197.63.238`；
3. `cd ~/ep-project && bash start.sh real`（会自动停旧服务，避免双实例互踢）；
4. 浏览器登录 admin/admin123，驾驶舱确认：画面在动、深度图、检测、急停各试一下；
5. 进「巡检任务」页，每边填 `0.3`，点「跑真机一圈」，确认；
6. 镜头跟着机器人走完 4 边 + 4 个 90°，页面显示 8 步全 ok + 4 张角照片；
7. 停止录屏，**这段单独保存，不剪**；失败步骤当场说明，不要重录掩盖。

## B. 卡死前后对比录屏（约 6 分钟）

> 机械臂周围清空；旧版堆积后会有十几秒动作延迟，属预期。

```bash
# B1 旧版复现（会看到第 37 条 10 秒超时）
pkill -9 -f services.control.server
EPCARE_LEGACY=1 EP_IP=10.197.63.238 nohup ep38/bin/python -m uvicorn \
  services.control.server:app --host 127.0.0.1 --port 8001 > logs/control_legacy.log 2>&1 &
sleep 4
curl -s -X POST http://127.0.0.1:8001/connect -H 'Content-Type: application/json' -d '{"mode":"real"}'
ai312/bin/python scripts/repro_pileup.py --n 36 --tag before

# B2 新版对比（33×429，探测 0.4 秒）
pkill -9 -f services.control.server
bash start.sh real
ai312/bin/python scripts/repro_pileup.py --n 36 --tag after
```

- 展示 `/state` 里的 `queue:{max:2,legacy:false}`；
- 口播：429 是主动限流，不是故障；旧版只能重启。

## C. 20 张测距 pilot（约 25 分钟）

1. 保持新版服务连接；量相机高度/俯仰、地砖边长（默认 0.6m）；
2. 采集（先瓷砖 10 张，再木地板 10 张；中途 `q` 可退，下次续采）：

```bash
ai312/bin/python scripts/collect_ranging_data.py --out data/ep_ranging --n 20 \
  --tile-m 0.6 --camera-height 0.25 --camera-pitch 0
```

3. 每张：摆物体 → 回车拍照 → 输入 `水瓶:1.2 盒子:2t 收纳包:0.5` → **点每个物体底部贴地点**；
4. 采完停掉服务（或加 `--cpu`）跑评测：

```bash
ai312/bin/python scripts/eval_ep_ranging.py          # 建议先停服务，避免抢 MPS
# 或
ai312/bin/python scripts/eval_ep_ranging.py --cpu
```

5. 产出 `results/ep_ranging_eval.md`，回填报告：

```bash
ai312/bin/python scripts/update_report_pilot.py
cp submission/2026-11-10/01_进度报告.md ~/Desktop/待审阅_11-10提交/
```

## D. 回去后交材料（周二 24:00 前）

- [ ] 周视频 5 分钟：开头 `git log --oneline -1`；含卡死前后对比 + 巡检片段 + pilot 结果表；
- [ ] 完整巡检录屏单独文件（A 段原始文件）；
- [ ] 进度报告（pilot 表已回填）；
- [ ] 日志总结：自己写/说，不贴 AI 原文；
- [ ] 桌面 `待审阅_11-10提交/` 里 01/02/03 + evidence + 录屏；私信王老师。

## 失败预案

- 机器人连不上：先 ping，再重启机器人；不要同时起两个控制服务；
- 相机没画面：只重连一次；反复开关流会坏视频模块，需重启机器人；
- 测距点击窗口打不开：确认在 Mac 本地图形界面运行，不是 SSH；
- 20 张采不完：至少采 12 张（8 训练/4 测试）再跑评测，报告里如实写数量。

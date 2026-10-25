给独居老人家庭和养老机构用的地面巡检整理机器人：RoboMaster EP 按设定路线巡检房间，用摄像头找出地上容易绊倒人的杂物，能捡的用机械爪放回这家人习惯的位置，捡不了的拍照告警，还能听懂一句「帮我找一下奶奶的老花镜」并去找。

# EPCare · 基于 RoboMaster EP 的居家地面巡检整理机器人

**毕设题目**：基于单目深度估计、开放词汇视觉定位与大模型偏好归纳的居家地面巡检整理机器人系统设计与实现

## 这是做什么的

老年人跌倒的主要诱因之一是地上的拖鞋、杂物和电线；老人还常找不到老花镜、药盒、遥控器。本系统用一台 RoboMaster EP 解决这件事：

- **巡检**：按房间路线巡检，网页上能看到第一人称实时画面、每个物体的识别框和距离；
- **整理**：能捡的杂物用机械爪捡起，依据这户人家的收纳习惯放回对应位置；捡不了的（电线、水渍、大件）拍照告警；
- **找东西**：家属说一句中文描述，机器人沿路线寻找并报告位置或直接取回。

## 三个 AI 功能（每项都要复现一篇论文并做出评测）

| 功能 | 复现对象 | 一句话说明 |
|---|---|---|
| F1 单目深度估计 | Depth Anything V2 (NeurIPS 2024) | 只用普通摄像头估计每个像素的距离，判断能不能走、够不够得着 |
| F2 开放词汇定位 | Grounding DINO (ECCV 2024) | 用文字描述直接在画面里找东西，不用为每类物品单独训练 |
| F3 偏好归纳规划 | TidyBot (Autonomous Robots 2023) | 大模型从家属给的几条示例归纳收纳习惯，生成可检查、可预演的整理计划 |

## 当前进度（阶段 1 · 复现，10/18–11/10）

- ✅ 2026-10-25 EP 机械臂「1 号舵机过载」故障修复完毕，真机连接测试通过（详见 [docs/ep_repair.md](docs/ep_repair.md)）
- ✅ 2026-10-25 Mac (Apple Silicon) 开发环境搭建完成，SDK 的 macOS 适配脚本入库
- ⏳ F1 / F2 / F3 论文复现进行中（NYU-D、COCO、TidyBot 基准）
- ⏳ 仿真环境（CoppeliaSim 4.10 + robomaster_sim）与网页系统骨架

每日进展记录在 [docs/worklog.md](docs/worklog.md)。

## 快速开始（Mac / Apple Silicon）

```bash
# 1. 创建环境并安装机器人控制环境（uv + Python 3.8）
uv venv --python 3.8 ep38 && uv venv --python 3.12 ai312
bash scripts/install_robomaster_mac.sh ep38   # robomaster SDK 无官方 macOS 包，脚本会拆包打补丁安装

# 2. 连接 EP（路由器组网，首次扫码；手机热点即可当路由器）
ep38/bin/python conn_test.py sta --ssid <Wi-Fi名> --password <密码>
# 机器人已在网内时重连：
ep38/bin/python conn_test.py sta --skip-qrcode
```

成功输出固件版本、SN 和电量即连接正常。`conn_test.py ap` 为 Wi-Fi 直连模式（Mac 会断外网）。

## 仓库结构

```
conn_test.py                  真机连接测试（STA 扫码组网 / 重连，读版本 SN 电量）
scripts/install_robomaster_mac.sh   robomaster SDK 的 Apple Silicon 安装脚本（拆包+补丁）
docs/ep_repair.md             EP 机械臂故障排查与修复记录
docs/worklog.md               开发日志（每天更新）
REPRO.md                      复现说明：环境、可行性、术语表
```

## 环境与硬件

- 机器人：RoboMaster EP（底盘 + 机械臂 + 机械爪 + 摄像头），官方 Python SDK 只支持 Python 3.6–3.8
- 开发机：Mac mini (Apple M6, 16GB)，控制服务用 `ep38`（Python 3.8），AI 模型用 `ai312`（Python 3.12 + PyTorch MPS）
- 已知限制：官方 SDK 的视频流解码器仅发布 Linux/Windows 二进制，macOS 上 `camera.start_video_stream` 不可用；视频流将改走 RTMP 拉流试验，或由 Windows 台式机承担机器人控制服务（与后端以 HTTP/WebSocket 通信，符合系统架构设计）

## 许可说明

本项目代码许可见 LICENSE（待补）。所用第三方论文代码与数据集（Depth Anything V2、Grounding DINO、TidyBot、NYU Depth V2、COCO、RefCOCO 等）的许可与引用要求将在 REPRO.md 中逐个列明；项目仅用于教学与研究。

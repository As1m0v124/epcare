# REPRO.md — 复现说明

> 目标：别人拉下本仓库，按本文档能复算出论文对照数字。持续更新。
> 毕设要求：本文档开头写「可行性五关」，随后是术语表与本机配置。

## 一、可行性五关（自评，10/20）

| 关卡 | 自评 | 说明 |
|---|---|---|
| 起点 | ✅ 已过 | 系统框架（网页 + CLI + MCP）与最短路规划是熟悉领域；三个 AI 功能按「下载 → 运行 → 对比论文」推进，均有现成代码与公开权重 |
| 数据 | 🔄 进行中 | 复现数据（NYU-D / DA-2K / COCO / RefCOCO / TidyBot 基准）来自国内网盘，待下载校验；场景数据（200 张测距图、300 张标注图、100 条指令、40 个中文场景）第 2 周起自采 |
| 硬件 | ✅ 已过 | EP 机械臂「1 号舵机过载」已修复（见 docs/ep_repair.md），真机连接测试通过；仿真环境 CoppeliaSim 4.10 第 2 周补齐 |
| 算力 | ✅ 已过 | Mac mini M6 跑推理评测（MPS 已验证可用）；大规模微调用 RTX 5070 台式机或 Kaggle 免费 GPU，零花费 |
| 许可 | 🔄 进行中 | README 已列说明；各数据集/权重许可将在本文件逐个补全（NYU-D 仅限研究；DA-V2 的 B/L 权重 CC BY-NC，仅非商业研究） |

## 二、本机配置

- 机器：Mac mini，Apple M6，16GB 统一内存，macOS 27 (darwin 27.0.0, arm64)
- 环境管理：uv（Python 3.8.20 + 3.12.15）
  - `ep38`：机器人控制，robomaster 0.1.1.68（官方无 macOS 包，见下方补丁说明）+ numpy/netaddr/netifaces/myqr
  - `ai312`：AI 模型，torch 2.14.1 + torchvision + transformers 5.20.2，MPS 加速可用
- 机器人连接：路由器组网（手机热点当路由器），SDK `conn_type='sta'`；直连模式 `conn_type='ap'`（会断外网）；USB(rndis) 在 macOS 不可用
- 安装脚本：`scripts/install_robomaster_mac.sh`（拆 manylinux wheel + 打补丁，一条命令复现）

### robomaster SDK 的 macOS 补丁（3 个）

1. `media.py`：`import libmedia_codec` / `import cv2` 加 try/except（包内唯一编译模块是 Linux 专用闭源视频解码器）；
2. `media.py`：解码器改按需创建，无解码器时 `start_video_stream/start_audio_stream` 明确报错（否则 `initialize` 即崩）；
3. `conn.py`：连接类型比较 `is` → `==`（命令行传入的字符串与内部常量非同一对象，导致 STA 连接三分支落空）。

### 已知平台限制

官方 `camera.start_video_stream` 在 macOS 不可用。备选：RTMP 拉流试验（`rtmp://192.168.2.1/live`，未证实）；或将机器人控制服务放 Windows 台式机，与后端以 HTTP/WebSocket 通信（系统架构本就如此设计）。

## 三、数据与权重

来源：国内网盘（百度网盘，提取码见毕设规划 8.1⑦）；下载后用 `shasum -a 256` 对照 `SHA256SUMS` 校验。清单：

| 用途 | 内容 | 状态 |
|---|---|---|
| F1 | NYU Depth V2 labeled.mat (~2.8GB) + splits.mat | ☐ 待下载 |
| F1 | DA-2K.zip (~680MB) | ☐ 待下载 |
| F1/F2 | Depth Anything V2 ViT-S (~100MB)、Grounding DINO Swin-T (~660MB)、bert-base-uncased (~440MB) | ☐ 待下载 |
| F2 | COCO val2017 图片+标注 (~1.3GB)、RefCOCO parquet | ☐ 待下载 |
| F3 | TidyBot 仓库压缩包（benchmark/scenarios.yml，96 场景） | ☐ 待下载 |

## 四、术语表

> 第 1 周要求：用 AI 辅助学完以下概念并写进本节。TODO。

- [ ] 麦轮底盘运动
- [ ] 机械臂工作空间
- [ ] 相机内参
- [ ] 单目深度 / 相对深度与真实距离
- [ ] AbsRel、δ1
- [ ] 目标检测、AP
- [ ] 开放词汇检测、指代表达理解
- [ ] 归纳推理

## 五、复算指引

复现启动后补全：每项功能「一条命令复算」的说明与预期输出。

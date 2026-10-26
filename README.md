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

- ✅ 2026-10-25 EP 机械臂「1 号舵机过载」修复完毕，**真机完整自检通过**：底盘前后左右各 0.5m、机械爪开合×3、前后舵机 +35mm（87→122）、上下舵机 +18mm（75→93）（详见 [docs/ep_repair.md](docs/ep_repair.md)）
- ✅ 2026-10-25 Mac (Apple Silicon) 开发环境搭建完成；SDK macOS 适配脚本入库，**视频流用 TCP 40921 直连 H.264 + PyAV 解码解决**（官方解码器仅 Linux/Windows）
- ✅ 2026-10-25 三项复现首轮出数：F1 AbsRel **0.0624** / δ1 **0.954**（论文 0.053 / 0.973）；F2 AP **43.4**（前 500 张）/ **40.8**（全量 4952 张，论文 48.4）；F3 **46.7% / 63.0%**（论文 78.5% / 91.2%，本地小模型）——详见 [docs/week1_report.md](docs/week1_report.md)
- ✅ 2026-10-25 EP 实拍 10 张实验室照片：深度图 + 5 句中文描述的开放词汇检测（80 个框）+ CSV（见 `results/photos_demo/` 与 `archive/`）
- ⏳ 下一步：仿真环境（第 2 周在台式机）、系统骨架（控制服务 + 后端 + 实时驾驶舱）

每日进展记录在 [docs/worklog.md](docs/worklog.md)，错例分析见 [docs/f1_error_analysis.md](docs/f1_error_analysis.md)，错题本见 [LESSONS.md](LESSONS.md)。

## 复算

```bash
ai312/bin/python week1.py    # 一条命令跑完第 1 周全部指标（详见 REPRO.md）
```

## 系统（网页 + CLI + MCP）

```bash
bash start.sh replay     # 回放模式（开发/演示，不动真机）：控制服务:8001 + 后端:8000 + 打开浏览器
bash start.sh real       # 真机模式（STA 组网；机器人需上电并加入同一 Wi-Fi）
# 浏览器 http://127.0.0.1:8000  演示账号 admin/admin123 · caregiver1/care123 · family1/family123
```

页面：数据看板、实时驾驶舱（实时画面/深度图/检测/急停/键盘遥控）、巡检任务、找东西、
家庭收纳习惯、房间与地标、告警中心、评测与数据、设备与安全、设置/审计、侧边栏助手。

- 安全由控制服务强制：急停后拒绝一切动作（仅管理员可解除）、限速、单次位移与机械臂限幅、
  低电量拒动、全部动作写 `logs/control_audit.jsonl`；
- CLI（ai312 环境）：`ai312/bin/python cli/epcare.py status | find "水瓶" | depth --image x.jpg --out d.png | patrol --room 客厅 --dry-run | tidy-rules --household f.txt | eval`；
- MCP：`ai312/bin/python mcp/epcare_mcp.py`（stdio JSON-RPC，工具：epcare_status/find/depth/patrol_plan/tidy_rules）；
- 冒烟测试：`bash tests_smoke.sh`（需先 `start.sh replay`）。

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
conn_test.py                    真机连接测试（STA 扫码组网 / 重连，读版本 SN 电量）
ep_selfcheck.py                 真机自检（连接/电量/视频流存图/底盘/机械爪/机械臂逐舵机）
week1.py                        一条命令跑完第 1 周全部指标与照片演示
scripts/install_robomaster_mac.sh   robomaster SDK 的 Apple Silicon 安装脚本（拆包+补丁）
scripts/eval_depth_nyu.py       F1 评测（NYU-D 654 张，AbsRel/δ1）
scripts/eval_gdino_coco500.py   F2 评测（COCO 前 500 张 / 全量，零样本 AP）
scripts/eval_tidybot.py         F3 评测（TidyBot 基准，两种提示方法）
scripts/week1_photos_demo.py    EP 实拍 10 张：深度图 + 检测 + CSV
docs/ep_repair.md               机械臂故障排查与修复/自检记录
docs/worklog.md                 开发日志（每天更新）
docs/f1_error_analysis.md       F1 十个错例分析
LESSONS.md                      错题本（Seen 计数，3 天复发升级为硬规则）
REPRO.md                        复现说明：环境、数据来源、评测口径、术语表
results/                        指标结果（json/csv）与照片演示输出
archive/2026-10-25_week1/       第 1 周交付物本地归档（照片、深度图、检测 CSV、校验清单）
submission/2026-10-27/          首次对齐提交材料（进度报告、提纲、清单）
```

## 环境与硬件

- 机器人：RoboMaster EP（底盘 + 机械臂 + 机械爪 + 摄像头），官方 Python SDK 只支持 Python 3.6–3.8
- 开发机：Mac mini (Apple M6, 16GB)，控制服务用 `ep38`（Python 3.8），AI 模型用 `ai312`（Python 3.12 + PyTorch MPS）
- 已知限制：官方 SDK 的视频解码器仅发布 Linux/Windows 二进制。**本项目已绕过**：SDK 只负责发开流命令，视频数据从 **TCP 40921 直连读取标准 H.264（Annex-B）**，用 PyAV 在 macOS 原生解码（见 REPRO.md「视频流：macOS 原生方案」）。

## 许可说明

本项目代码许可见 LICENSE（待补）。所用第三方论文代码与数据集（Depth Anything V2、Grounding DINO、TidyBot、NYU Depth V2、COCO、RefCOCO 等）的许可与引用要求将在 REPRO.md 中逐个列明；项目仅用于教学与研究。

# 第 1 周进度报告（2026-10-25，第一次对齐用）

> 对齐时间：10/27（周二）20:00。交付物清单见毕设规划第 12 节。

## 一、本周做了什么

1. **EP 机械臂「1 号舵机过载」修复完毕**，修复后真机 SDK 连接测试通过：固件 01.01.1150、SN 3JKCK2R00304Q7、电量 84%。记录见 `docs/ep_repair.md`。
2. **开发环境（Mac mini, Apple M6/16GB）**：
   - `ep38`（Python 3.8，机器人控制）+ `ai312`（Python 3.12，PyTorch/Transformers，MPS 可用）双环境；
   - robomaster SDK 无 macOS 官方包 → 拆包安装方案脚本化（`scripts/install_robomaster_mac.sh`），含 3 个必要补丁；
   - 真机连接链路：手机热点当路由器 + STA 组网（SDK ConnectionHelper 扫码），`conn_test.py` 可复现。
3. **F1/F2/F3 复现工程**：
   - 评测脚本三件套（`scripts/eval_depth_nyu.py`、`eval_gdino_coco500.py`、`eval_tidybot.py`），`week1.py` 一键汇总；
   - 数据获取：直连 GitHub/COCO/NYU 受限，改用 代理 + hf-mirror + ModelScope 多源并行；
   - F3 本地模型：Qwen2.5-3B-Instruct（ModelScope 下载，替代论文停用的 OpenAI 接口；零成本离线，符合规划「本机小模型作离线备用」）。
4. **仓库与过程可见**：GitHub 仓库 [As1m0v124/epcare](https://github.com/As1m0v124/epcare) 上线，多个逻辑提交；日志 `docs/worklog.md`；术语表进 `REPRO.md`。

## 二、指标（对照论文）

| 功能 | 指标 | 复算结果 | 论文 |
|---|---|---|---|
| F1 | NYU-D 654 张 AbsRel / δ1 | （待跑） | 0.053 / 0.973 |
| F2 | COCO val2017 前 500 张零样本 AP | （待跑） | 48.4 |
| F3 | TidyBot 20 场景：只看示例 / 先归纳再推断 | （待跑） | 78.5% / 91.2% |

## 三、遇到的问题与处理

| 问题 | 处理 |
|---|---|
| robomaster SDK 无 macOS wheel；唯一编译模块是 Linux 视频解码器 | 拆包安装纯 Python 部分 + 3 补丁；视频流在 macOS 不可用，备选 RTMP 试验或台式机跑控制服务（架构允许） |
| SDK `initialize` 崩溃（解码器急切创建） | 改为按需创建；已固化进安装脚本 |
| SDK 连接类型 `is` 比较 bug（命令行传参连不上） | 改 `==`；已固化 |
| 下载通道受限（GitHub/COCO/NYU 直连极慢或 502） | 代理 + hf-mirror + ModelScope 多源、多线程分块续传（`scripts/fast_download.py`） |
| 机器人当前不在线（网络切换后） | 动作自检与 EP 实拍照片待机器人上线后执行（见第四节） |

## 四、未完成项（与原因）

1. **`ep_selfcheck.py` 动作自检**（底盘 0.3m/机械爪/机械臂）：脚本已就绪（`ep_selfcheck.py`，含 `--motion` 与安全确认），等机器人上电入网后现场执行。
2. **EP 摄像头 10 张地面照片 + 深度图/检测 CSV**：① 机器人需在线；② macOS 上 SDK 视频流不可用（闭源解码器），需先试 RTMP 拉取（`rtmp://<机器人IP>/live`）或改由台式机采集。
3. **仿真（CoppeliaSim 4.10 + robomaster_sim）**：macOS 无插件二进制，计划在 RTX 5070 台式机补（规划允许）。
4. **周视频与完整录屏**：待指标跑出后录制（视频开头展示 commit 编号）。

## 五、下周计划（10/28–11/03）

1. 指标收尾：F1 654 张、F2 500 张、F3 20 场景，与论文逐项对比并写差异分析；
2. 机器人上线后跑 `ep_selfcheck.py --motion`，补齐 `ep_repair.md` 自检结论；
3. EP 实拍 10 张地面照片（先试 RTMP），跑 F1 深度图与 F2 找东西演示；
4. 10 个错例分析（深度错/框错/放错位置），进错题本；
5. 启动阶段 2 的数据采集方案（模拟居家区域、标注工具选型）。

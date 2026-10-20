# 开发日志（Worklog）

> 规则：每天更新；记录「做了什么 / 指标数字 / 问题与解决 / 明日计划」。
> 错题本（LESSONS.md）另记出现次数，同一条教训在 3 个不同日子出现升级为硬规则。

---

## 2026-10-20（周二）｜环境日 + 真机连通日

**本周目标**：修复 EP 机械臂 → 跑通真机连接 → 搭好双环境 → 启动 F1/F2/F3 复现。
**今日投入**：约 1 天。

### ✅ 完成了什么

1. **EP 机械臂「1 号舵机过载」故障修复完毕**（第 1 周头等任务）。排查与修复记录见 [docs/ep_repair.md](ep_repair.md)。
2. **GitHub 仓库建立并推送**：[As1m0v124/epcare](https://github.com/As1m0v124/epcare)，今日工作分 4 个逻辑提交入库；git 推送走本地代理（127.0.0.1:7897，直连 GitHub 超时）。
2. **真机连接测试通过**（修复后首次验证）：
   - 连接方式：路由器组网（手机热点当路由器），Mac 与 EP 同网，Mac 不断外网；
   - 固件版本 **01.01.1150**，机器人 SN **3JKCK2R00304Q7**，电量 **84%**；
   - 连接脚本 `conn_test.py` 入库：支持 STA 扫码首次组网（SDK 自带 ConnectionHelper 生成二维码，机器人相机扫码入网）与 `--skip-qrcode` 快速重连，自动读版本/SN/电量。
3. **开发环境搭建完成**（Mac mini, Apple M6, 16GB）：
   - `uv` 建 `ep38`（Python 3.8，机器人控制）/ `ai312`（Python 3.12，AI 模型）双环境；
   - ai312 已装 PyTorch + Transformers，**MPS 显卡加速验证可用**；
   - robomaster SDK 官方无 macOS 包 → 写了 `scripts/install_robomaster_mac.sh` 拆包安装并打补丁，一条命令可复现。

### 🔧 解决的问题（3 个，含根因）

| 问题 | 根因 | 解法 |
|---|---|---|
| `uv pip install robomaster` 报「无匹配平台的 wheel」 | DJI 官方只发布 Linux/Windows wheel；包内唯一编译模块是 Linux x86_64 视频解码器 libmedia_codec（闭源） | 拆开 manylinux wheel，把纯 Python 部分装进 ep38，对 `media.py` 两处 import 打容错补丁；依赖 4 个纯 Python 包单独装（netifaces 源码编译约 10 分钟） |
| SDK `initialize()` 直接崩溃，控制全不可用 | 初始化相机模块时**急切创建**视频解码器，而 macOS 上 libmedia_codec 不存在 | 解码器改为按需创建；`start_video_stream/start_audio_stream` 在无解码器时明确报错返回，不再拖垮连接 |
| 命令行传参连不上机器人（内联脚本却能连） | SDK 用 `is`（对象身份）比较连接类型；从命令行传入的 `'sta'` 与内部常量不是同一字符串对象，三个分支全部落空 | `conn.py` 三处 `is` 改为 `==`（SDK bug，上游可报告） |

另发现：EP 电量为**订阅推送式**接口（非一问一答），需 `sub_battery_info(freq=1, callback=...)` 订阅后延时读取。

### ⚠️ 已知限制与对策

- 官方 SDK 的 `camera.start_video_stream` 在 macOS 永远不可用（解码器闭源无法编译）。对策：① 试验 RTMP 拉流（直连模式 `rtmp://192.168.2.1/live`，待验证）；② 机器人控制服务放 Windows 台式机（SDK 原生支持），与 Mac 后端走 HTTP/WebSocket——符合系统架构设计。
- 实用技巧：机器人换网后不知道 IP 时，扫局域网 **TCP 40923** 端口即可定位。

### 📊 指标

复现未开始，暂无评测数字。（对照目标：F1 AbsRel 0.053 / δ1 0.973；F2 COCO 零样本 AP 48.4；F3 TidyBot 78.5% / 91.2%）

### 📌 明日计划

1. 百度网盘下载数据与权重（NYU-D、DA-2K、COCO val2017、RefCOCO、模型权重），SHA256 校验；
2. F1：Depth Anything V2-S 在 NYU-D 654 张测试图上复算 AbsRel / δ1；
3. 编写 `ep_selfcheck.py` 动作部分（底盘 0.3m、机械爪开合、机械臂小范围），现场安全确认后执行；
4. 开始每日提交（今日已建仓，从明天起保持「每天至少 1 次有意义提交」）。

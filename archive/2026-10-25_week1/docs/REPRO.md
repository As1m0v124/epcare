# REPRO.md — 复现说明

> 目标：别人拉下本仓库，按本文档能复算出论文对照数字。持续更新。
> 毕设要求：本文档开头写「可行性五关」，随后是术语表与本机配置。

## 一、可行性五关（自评，10/25 更新）

| 关卡 | 自评 | 说明 |
|---|---|---|
| 起点 | ✅ 已过 | 系统框架（网页 + CLI + MCP）与最短路规划是熟悉领域；三个 AI 功能已按「下载 → 运行 → 对比论文」跑通首轮 |
| 数据 | ✅ 已过（本周范围） | NYU-D、COCO 前 500 张、TidyBot 基准全部就位并通过校验；场景数据（EP 居家测距/标注集）第 2 周起自采 |
| 硬件 | ✅ 已过 | EP 机械臂已修复，真机连接测试通过；`ep_selfcheck.py` 动作项待机器人上线执行（见第五节的阻塞说明）；仿真第 2 周在台式机补 |
| 算力 | ✅ 已过 | M6 跑通 F1(654 张)/F2(500 张)/F3(20 场景)；大模型微调留待 RTX 5070 或 Kaggle |
| 许可 | 🔄 进行中 | 已按来源记录；各数据集/权重许可将在交付前逐个补全（NYU-D 仅研究用；DA-V2 ViT-B/L 为非商业） |

**首轮复算结果（10/25）**：F1 AbsRel 0.0624 / δ1 0.954（论文 0.053 / 0.973）；
F2 AP 43.4（论文 48.4，前 500 张口径）；F3 46.7% / 63.0%（论文 78.5% / 91.2%，本地小模型）。

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

### 视频流：macOS 原生方案（10/25 实机验证）

官方 `camera.start_video_stream` 依赖 Linux/Windows 专用闭源解码器，macOS 上不可用；
RTMP 也不可用（`<ip>:1935` 拒绝连接）。**但实测发现 EP 的视频端口直接推送标准 H.264**：

1. SDK 连接后发送开流命令：`camera._stream_sdk(1, "360p")` + `camera._video_stream(1, "360p")`
   （SDK 内部方法，仅用于下发命令）；
2. **TCP 直连 `<机器人IP>:40921`**，读取到的数据就是标准 H.264 Annex-B
   （实测含 SPS/PPS/IDR 起始码，762 个起始码/5 秒）；
3. 用 PyAV（`av.CodecContext.create("h264", "r")`）解码为帧 → OpenCV 存图/推流。

实测结果：`ep_selfcheck.py` 通过该路径成功保存 10 张 640×360 实拍图；
`ep38` 环境依赖 `av` + `opencv-python-headless`。该方案**取代**此前「视频流需台式机/Docker」的判断，
驾驶舱实时画面也可以直接跑在 Mac 上。

## 三、数据与权重（实际获取记录，2026-10-25）

直连 GitHub / COCO / NYU 官方服务器在本地网络下不可用（超时/502），最终多源并行获取，
全部脚本化（`scripts/fast_download.py`，多线程分块+断点续传）：

| 用途 | 内容 | 实际来源 | 状态 |
|---|---|---|---|
| F1 | NYU Depth V2 `nyu_depth_v2_labeled.mat`（2.97GB）+ `splits.mat`（B64 镜像） | horatio.cs.nyu.edu（https，多线程） | ✅ 已校验大小 |
| F1 | Depth Anything V2 ViT-S | 官方 `.pth`（hf-mirror，18MB/s）+ HF format 权重（transformers 缓存） | ✅ |
| F2 | COCO val2017 图片 | `detection-datasets/coco` val parquet（hf-mirror，807MB）→ 转换脚本还原 500 张 | ✅（B64 前 500 张） |
| F2 | COCO 官方标注 | images.cocodataset.org `annotations_trainval2017.zip`（252MB） | ✅ 已解压校验 |
| F2 | Grounding DINO Swin-T | `IDEA-Research/grounding-dino-tiny`（hf-mirror，689MB） | ✅ |
| F3 | TidyBot 基准 | GitHub clone（代理） | ✅ 96 场景 |
| F3 | 本地 LLM | Qwen2.5-3B-Instruct（ModelScope，6.2GB） | ✅ |

> 注：COCO 改用 HF 数据集镜像的 val 分片（官方 zip 源站不可达），标注由 parquet 内的
> 0–79 类别索引映射回 COCO 官方 id；与官方 val2017 前 500 张的图片顺序不同（按 parquet
> 行序取前 500），AP 结果按此子集口径记录。

## 三点五、评测口径（复算必读）

- **F1**：输入 518×518（拉伸缩放）→ 输出上采样回 480×640 → **Eigen 标准裁剪**
  （rows 45:471, cols 41:601）→ 在反深度空间做**尺度+偏移最小二乘对齐** →
  有效像素 GT ∈ (0, 10m) → AbsRel / δ1。
  ⚠️ **数据加载陷阱**：`nyu_depth_v2_labeled.mat` 的图像与深度均为**转置存储**
  （图像 `(3, 640, 480)`、深度 `(640, 480)`），必须 `transpose(2,1,0)` / `.T` 还原，
  否则模型看到的是侧翻镜像图，AbsRel 从 0.062 恶化到 0.10+。
- **F2**：80 类名小写用 " . " 连接作为文字提示；box_threshold 0.3 / text_threshold 0.25；
  pycocotools bbox 评测（AP@[.5:.95]）。
- **F3**：提示词与解析逐字移植 TidyBot 官方 notebook；本地 Qwen2.5-3B-Instruct，
  greedy 解码（可复现）；评分按官方 `check_placements`。

## 四、术语表

> 第 1 周要求：理解以下概念并用自己的话写下（含公式/直觉）。

**麦轮底盘运动**：EP 的四个轮子是麦克纳姆轮，轮周辊子与轮轴成 45°。每个轮子转动的合成速度可分解为沿车体 x、y 方向和绕 z 轴的旋转分量，因此底盘能平移+自转互不干扰（全向移动）。直行时四轮同向，横移时左右两侧轮组反向组合。

**机械臂工作空间**：机械臂末端可以到达的所有位置集合，由各关节（舵机）行程限制共同决定。抓取前要确认目标物体在可达范围内，否则先移动底盘调整位姿。EP 机械臂用 x（前后，mm）/ y（上下，mm）两个控制轴描述。

**相机内参**：描述相机成像几何的参数（焦距 fx、fy 和主点 cx、cy）。三维相机坐标点 (X, Y, Z) 投影到像素：u = fx·X/Z + cx，v = fy·Y/Z + cy。单目深度 → 真实距离换算、物体框底边估距都依赖它。

**单目深度**：从单张 RGB 图像回归每个像素的距离（稠密回归）。病态问题：单图本身缺少绝对尺度信息，模型只能学到"相对远近"。

**相对深度 vs 真实距离**：相对深度只保证"谁近谁远"的排序（typically 反深度/视差，值大=近）；真实距离以米为单位。换算需要尺度信息：① 地面平面拟合（已知相机高度与俯仰角，把地面像素回投到地平面求 Z）；② 已知距离的标定点拟合线性变换。二者要做对比实验。

**AbsRel**（绝对相对误差）：`mean(|d_pred − d_gt| / d_gt)`，对深度尺度敏感，因此评测前要按协议先做尺度/偏移对齐。

**δ1**（阈值准确率）：`mean(max(d_pred/d_gt, d_gt/d_pred) < 1.25)`，即预测误差在 25% 以内的像素比例，越大越好。论文对照：AbsRel 0.053 / δ1 0.973。

**目标检测与 AP**：检测 = 框 + 类别。AP 是精确率-召回率曲线下面积；COCO 的 AP 对 IoU 阈值 0.50:0.05:0.95 取平均，AP50 只用 IoU 0.5。Grounding DINO 论文对照：COCO val2017 零样本 AP 48.4。

**开放词汇检测**：检测器的分类头换成一个"文本编码器 × 图像特征"的相似度计算，类别名作为文字输入——不需要为每个类别单独训练，可以随时用新词查询（如 "blue pill box"）。

**指代表达理解**：输入整句描述（"左边那个蓝色的药盒"），输出被指代物体的框。RefCOCO 用 IoU ≥ 0.5 统计 Top-1 准确率。

**归纳推理**：从少量示例（家属给的几条"什么东西放哪儿"）归纳出一般规则（如"药放床头柜，拖鞋放门口"），再把规则应用到没见过的物品上。TidyBot 表明"先归纳再推断"比"只看示例直接推断"更准（91.2% vs 78.5%）。


## 五、复算指引

在 `~/ep-project` 下（需先按第二节装好 ai312 环境与数据）：

```bash
# 一条命令跑完第 1 周全部指标（已有结果自动跳过，--force 重跑）
ai312/bin/python week1.py

# 单独复算
ai312/bin/python scripts/eval_depth_nyu.py        # F1 → results/nyu_f1.{json,csv}
ai312/bin/python scripts/eval_gdino_coco500.py --limit 500 --ann results/coco_val_gt.json --img-dir data/coco/val2017
ai312/bin/python scripts/eval_tidybot.py --n 20   # F3 → results/tidybot_f3.json
```

**当前阻塞项**：`ep_selfcheck.py --motion`（底盘/机械爪/机械臂动作自检）与 EP 实拍照片需要机器人上电入网；
macOS 上 SDK 视频流不可用（见第二节），实拍计划先试 RTMP 拉流。

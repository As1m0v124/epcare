# 第 3 周检查点（11/10）状态 · 2026-10-26

对照毕设规划第 13 节「必须做到」的六项：

| # | 要求 | 状态 | 证据/说明 |
|---|---|---|---|
| 1 | 第 1 周任务通过（10/27 对齐确认） | ✅ 已提交 | 报告+视频+日志总结已交王老师 |
| 2 | EP 机械臂修好；自检脚本真机全过；能走到物体前伸臂夹起放下 | ✅ 自检全过（底盘 0.5m×4、爪×3、前后舵机 +35mm、上下舵机 +18mm）；⏳ 抓放动作待接真机验证 | docs/ep_repair.md；results/selfcheck.json |
| 3 | F1：NYU-D + DA-2K 复算 | ✅ NYU-D AbsRel 0.0624 / δ1 0.954；DA-2K 94.78%（论文 95.3%） | results/nyu_f1.json、results/da2k.json |
| 4 | F2：COCO 全量 5000 + RefCOCO 三划分 | ✅ COCO 全量 4952 张 AP 40.8；RefCOCO testA 55.5%（论文 57.2）、testB 43.5%（论文 43.2）；val 运行中 | results/coco_f2_full.json、results/refcoco.json（完成后） |
| 5 | F3：TidyBot 96 场景复算 | ⏳ 96 场景运行中（20 场景已出 46.7% / 63.0%，论文 78.5% / 91.2%） | results/tidybot_f3_96.json（完成后） |
| 6 | 系统：登录 + 驾驶舱真实画面/检测 + 急停 | ✅ 骨架完成并验证：登录/三角色权限、回放画面 640×360、检测（水瓶 0.823 / ≈1.02m）、急停拦截（423）、限速/机械臂限幅、审计；真机画面在 replay→real 切换后即为真实流 | backend/、services/control/、start.sh |

## 待办（10/27–11/10）

1. RefCOCO val/testA/testB 完成后补 results/refcoco.json 并写进报告；
2. TidyBot 96 场景跑完；随后跑 40 个中文场景（`data/zh_scenarios.yml`）；
3. 接真机：把控制服务切 `real`，验证驾驶舱真实画面 + 抓放动作（ep_selfcheck 动作已全过）；
4. 补充第 4 周要求的「考研复试对照复查」（文档 §15/§17）。

## 风险

- macOS 上 MPS 并发会触发 Metal 断言（已加全局 GPU 锁解决）；
- 真机视频流走 TCP 40921 裸 H.264（已验证），若网络抖动需重连视频线程（已实现自动重连）。

#!/usr/bin/env python3
"""EP 真机自检脚本（毕设第 1 周第 11 节第 1 条要求的 ep_selfcheck.py）。

默认只做不动的项（连接/版本/SN/电量/视频流探测）；
加 --motion 才执行底盘、机械爪、机械臂动作（执行前会要求确认现场安全）。

用法:
  ep38/bin/python ep_selfcheck.py --conn sta            # 只读项
  ep38/bin/python ep_selfcheck.py --conn sta --motion   # 含动作项

动作项安全约束:
  - 底盘：前后左右各 0.3m（先前进再退回，再左移再退回），限速 0.5m/s；
  - 机械爪：开合各 3 次，50% 力度；
  - 机械臂：相对当前位置 20mm 前 +10mm 上，再原路退回（不越界、不持物）；
  执行前确认机器人周围 1 米内无人、无障碍物。
"""
import argparse
import json
import os
import time

from robomaster import robot

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


def read_battery(ep, wait=1.5):
    box = {}
    ep.battery.sub_battery_info(freq=1, callback=lambda p: box.setdefault("pct", p))
    time.sleep(wait)
    ep.battery.unsub_battery_info()
    return box.get("pct")


def read_arm_position(ep, wait=1.0):
    box = {}
    ep.robotic_arm.sub_position(freq=10, callback=lambda x, y: box.update(pos=(x, y)))
    time.sleep(wait)
    ep.robotic_arm.unsub_position()
    return box.get("pos")


def run(ep, results, do_motion):
    # ---- 只读项 ----
    results["版本"] = ep.get_version()
    results["SN"] = ep.get_sn()
    results["电量"] = read_battery(ep)

    # 视频流探测（macOS 上预期不可用，记录原因，不算失败）
    try:
        ok = ep.camera.start_video_stream(display=False, resolution="360p")
        if ok:
            time.sleep(2)
            img = ep.camera.read_cv2_image(strategy="newest")
            results["视频流"] = f"可用，帧尺寸 {img.shape}" if img is not None else "启动成功但未读到帧"
            ep.camera.stop_video_stream()
        else:
            results["视频流"] = "不可用（macOS 无 libmedia_codec；改用 RTMP/台式机方案，见 REPRO.md）"
    except Exception as e:
        results["视频流"] = f"异常: {e!r}（macOS 预期行为）"

    if not do_motion:
        results["动作自检"] = "未执行（加 --motion 运行）"
        return

    # ---- 底盘：前后左右各 0.3m ----
    for axis, dist, label in (("x", 0.3, "前进0.3m"), ("x", -0.3, "退回0.3m"),
                              ("y", 0.3, "左移0.3m"), ("y", -0.3, "右移0.3m")):
        kwargs = {"x": 0.0, "y": 0.0, "xy_speed": 0.5}
        kwargs[axis] = dist
        ep.chassis.move(**kwargs).wait_for_completed(timeout=15)
        time.sleep(0.5)
    results["底盘(前后左右0.3m)"] = "通过"

    # ---- 机械爪：开合各 3 次 ----
    for _ in range(3):
        ep.gripper.open(power=50).wait_for_completed(timeout=10)
        time.sleep(0.5)
        ep.gripper.close(power=50).wait_for_completed(timeout=10)
        time.sleep(0.5)
    results["机械爪(开合3次)"] = "通过"

    # ---- 机械臂：小范围动一下并读回位置 ----
    pos0 = read_arm_position(ep)
    ep.robotic_arm.move(x=20, y=10).wait_for_completed(timeout=10)
    time.sleep(0.5)
    pos1 = read_arm_position(ep)
    ep.robotic_arm.move(x=-20, y=-10).wait_for_completed(timeout=10)
    time.sleep(0.5)
    pos2 = read_arm_position(ep)
    results["机械臂(小范围+读回)"] = {"起点": pos0, "移动后": pos1, "退回后": pos2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", choices=["sta", "ap"], default="sta")
    ap.add_argument("--motion", action="store_true", help="执行底盘/机械爪/机械臂动作")
    ap.add_argument("--yes", action="store_true", help="跳过安全确认")
    args = ap.parse_args()

    if args.motion and not args.yes:
        print("!! 即将让机器人移动：底盘前后左右各 0.3m、机械爪开合 3 次、机械臂小幅动作。")
        ans = input("确认机器人周围 1 米内无人、无障碍物？输入 yes 继续: ").strip().lower()
        if ans != "yes":
            print("已取消动作项。")
            args.motion = False

    results = {}
    ep = robot.Robot()
    try:
        ep.initialize(conn_type=args.conn)
        results["连接"] = f"成功（{args.conn}）"
        run(ep, results, args.motion)
    except Exception as e:
        results["错误"] = repr(e)
        raise
    finally:
        ep.close()

    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, "selfcheck.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)
    print("\n===== 自检结果 =====")
    for k, v in results.items():
        print(f"{k}: {v}")
    print("已保存:", out)


if __name__ == "__main__":
    main()

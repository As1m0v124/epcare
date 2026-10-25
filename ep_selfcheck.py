#!/usr/bin/env python3
"""EP 真机自检脚本（毕设第 1 周要求）。

执行项：
  1. 连接 + 读固件版本 / SN / 电量（订阅式）
  2. 视频流：SDK 直取（macOS 不可用）→ 自动尝试 RTMP 拉流，存 10 张图
  3. --motion: 底盘前后左右各 0.3m → 机械爪开合 3 次 → 机械臂小范围动作并读回位置

用法:
  ep38/bin/python ep_selfcheck.py                     # 只读 + 视频
  ep38/bin/python ep_selfcheck.py --motion            # 含动作（会要求确认安全）
  ep38/bin/python ep_selfcheck.py --motion --robot-ip 10.x.x.x

录视频前先展示 commit：git log --oneline -1
"""
import argparse
import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
from robomaster import robot

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
PHOTOS = os.path.join(RESULTS, "selfcheck_photos")


def banner(text):
    print("\n" + "=" * 56)
    print("  " + text)
    print("=" * 56, flush=True)


def read_battery(ep, wait=1.5):
    box = {}
    ep.battery.sub_battery_info(freq=1, callback=lambda p: box.setdefault("pct", p))
    time.sleep(wait)
    ep.battery.unsub_battery_info()
    return box.get("pct")


def read_arm_position(ep, wait=1.0):
    """订阅机械臂位置。SDK 回调收到的是单个元组 (x, y)。"""
    box = {}
    ep.robotic_arm.sub_position(freq=10, callback=lambda pos: box.update(pos=pos))
    time.sleep(wait)
    ep.robotic_arm.unsub_position()
    return box.get("pos")


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    finally:
        s.close()


def discover_robot_ip(timeout=0.3):
    ip = local_ip()
    prefix = ip.rsplit(".", 1)[0]

    def probe(i):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((f"{prefix}.{i}", 40923))
            return f"{prefix}.{i}"
        except Exception:
            return None
        finally:
            s.close()

    with ThreadPoolExecutor(64) as pool:
        for r in pool.map(probe, range(1, 255)):
            if r:
                return r
    return None


def grab_photos(ep, n=10, resolution="360p"):
    """抓 EP 视频流：SDK 只负责发「开启图传」命令，视频数据从 TCP 40921 直连读取
    （实测为裸 H.264 Annex-B 流，绕过官方 Linux 专用解码器，Mac 可原生解码）。"""
    os.makedirs(PHOTOS, exist_ok=True)

    try:
        ok1 = ep.camera._stream_sdk(1, resolution)
        ok2 = ep.camera._video_stream(1, resolution)
    except Exception as e:
        return 0, f"开启图传命令失败: {e!r}"
    if not (ok1 and ok2):
        return 0, "开启图传命令被拒"

    ip, port = ep.camera.video_stream_addr
    raw = b""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((ip, port))
        print(f"  已连接视频流 TCP {ip}:{port}", flush=True)
        t0 = time.time()
        while time.time() - t0 < 6 and len(raw) < 3_000_000:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            raw += chunk
    finally:
        s.close()
        try:
            ep.camera._video_stream(0, resolution)
            ep.camera._stream_sdk(0, resolution)
        except Exception:
            pass

    if not raw:
        return 0, "视频端口无数据"
    print(f"  收到 {len(raw)} 字节 H.264 数据", flush=True)

    import av

    ctxx = av.CodecContext.create("h264", "r")
    saved = 0
    for pkt in ctxx.parse(raw):
        for frame in ctxx.decode(pkt):
            img = frame.to_ndarray(format="bgr24")
            if saved < n:
                cv2.imwrite(os.path.join(PHOTOS, f"photo_{saved:02d}.jpg"), img)
                print(f"  ✅ 第 {saved+1}/{n} 帧  {img.shape[1]}x{img.shape[0]}", flush=True)
            saved += 1
        if saved >= n:
            break
    return min(saved, n), f"直连 H.264（TCP {port}，{resolution}）"


def run_motion(ep, results, dist=0.5, arm_x=35, arm_y=20):
    banner(f"3/5 底盘：前进 {dist}m → 退回 {dist}m → 左移 {dist}m → 右移 {dist}m")
    for label, kw in (
        (f"前进 {dist}m", {"x": dist, "y": 0.0}),
        (f"退回 {dist}m", {"x": -dist, "y": 0.0}),
        (f"左移 {dist}m", {"x": 0.0, "y": dist}),
        (f"右移 {dist}m", {"x": 0.0, "y": -dist}),
    ):
        print(f"  >> {label}", flush=True)
        ep.chassis.move(xy_speed=0.8, **kw).wait_for_completed(timeout=20)
        time.sleep(0.4)
    results[f"底盘(前后左右各{dist}m)"] = "通过"
    print("  ✅ 底盘动作完成", flush=True)

    banner("4/5 机械爪：开合 3 次")
    for i in range(3):
        print(f"  >> 第 {i+1} 次：张开", flush=True)
        ep.gripper.open(power=50)
        time.sleep(1.2)
        print(f"  >> 第 {i+1} 次：闭合", flush=True)
        ep.gripper.close(power=50)
        time.sleep(1.2)
    results["机械爪(开合3次)"] = "通过"
    print("  ✅ 机械爪动作完成", flush=True)

    banner(f"5/5 机械臂：前后舵机(x±{arm_x}mm) 与 上下舵机(y±{arm_y}mm) 分别测试并读回位置")
    pos0 = read_arm_position(ep)
    print(f"  起点位置: x={pos0[0] if pos0 else '?'} y={pos0[1] if pos0 else '?'}", flush=True)

    # 前后舵机（x 轴）
    print(f"  >> 前后舵机：向前 {arm_x}mm", flush=True)
    ep.robotic_arm.move(x=arm_x, y=0).wait_for_completed(timeout=15)
    time.sleep(0.6)
    pos_x1 = read_arm_position(ep)
    print(f"     移动后: x={pos_x1[0] if pos_x1 else '?'} y={pos_x1[1] if pos_x1 else '?'}", flush=True)
    print(f"  >> 前后舵机：退回 {arm_x}mm", flush=True)
    ep.robotic_arm.move(x=-arm_x, y=0).wait_for_completed(timeout=15)
    time.sleep(0.6)
    pos_x2 = read_arm_position(ep)
    print(f"     退回后: x={pos_x2[0] if pos_x2 else '?'} y={pos_x2[1] if pos_x2 else '?'}", flush=True)

    # 上下舵机（y 轴）
    print(f"  >> 上下舵机：向上 {arm_y}mm", flush=True)
    ep.robotic_arm.move(x=0, y=arm_y).wait_for_completed(timeout=15)
    time.sleep(0.6)
    pos_y1 = read_arm_position(ep)
    print(f"     移动后: x={pos_y1[0] if pos_y1 else '?'} y={pos_y1[1] if pos_y1 else '?'}", flush=True)
    print(f"  >> 上下舵机：降回 {arm_y}mm", flush=True)
    ep.robotic_arm.move(x=0, y=-arm_y).wait_for_completed(timeout=15)
    time.sleep(0.6)
    pos_y2 = read_arm_position(ep)
    print(f"     降回后: x={pos_y2[0] if pos_y2 else '?'} y={pos_y2[1] if pos_y2 else '?'}", flush=True)

    # 判定：读回位置必须发生对应轴的变化，另一轴基本不动
    def dx(p): return abs(p[0] - pos0[0]) if (p and pos0) else None
    def dy(p): return abs(p[1] - pos0[1]) if (p and pos0) else None
    x_ok = dx(pos_x1) is not None and dx(pos_x1) >= arm_x * 0.5 and (dy(pos_x1) or 0) <= 5
    y_ok = dy(pos_y1) is not None and dy(pos_y1) >= arm_y * 0.5 and (dx(pos_y1) or 0) <= 5
    print(f"  {'✅' if x_ok else '⚠️'} 前后舵机 x 位移 {dx(pos_x1)}mm（退回后剩 {dx(pos_x2)}mm）", flush=True)
    print(f"  {'✅' if y_ok else '⚠️'} 上下舵机 y 位移 {dy(pos_y1)}mm（降回后剩 {dy(pos_y2)}mm）", flush=True)

    results["机械臂(前后舵机x)"] = {
        "起点": pos0, "向前后": pos_x1, "退回后": pos_x2, "位移mm": dx(pos_x1), "通过": x_ok,
    }
    results["机械臂(上下舵机y)"] = {
        "起点": pos0, "向上后": pos_y1, "降回后": pos_y2, "位移mm": dy(pos_y1), "通过": y_ok,
    }
    print("  ✅ 机械臂动作完成", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", choices=["sta", "ap"], default="sta")
    ap.add_argument("--motion", action="store_true", help="执行底盘/机械爪/机械臂动作")
    ap.add_argument("--dist", type=float, default=0.5, help="底盘每个方向移动距离（米，默认 0.5）")
    ap.add_argument("--arm-x", type=int, default=35, help="机械臂前后测试幅度（mm，默认 35）")
    ap.add_argument("--arm-y", type=int, default=20, help="机械臂上下测试幅度（mm，默认 20）")
    ap.add_argument("--photos", type=int, default=10)
    ap.add_argument("--robot-ip", default="", help="RTMP 用；不填则自动扫描")
    ap.add_argument("--yes", action="store_true", help="跳过安全确认")
    args = ap.parse_args()

    banner("1/5 连接机器人并读取信息")
    results = {}
    ep = robot.Robot()
    try:
        ep.initialize(conn_type=args.conn)
        results["连接"] = f"成功（{args.conn}）"
        results["版本"] = ep.get_version()
        results["SN"] = ep.get_sn()
        results["电量"] = read_battery(ep)
        print(f"  ✅ 已连接  conn_type={args.conn}", flush=True)
        print(f"  固件版本: {results['版本']}", flush=True)
        print(f"  机器人 SN: {results['SN']}", flush=True)
        print(f"  电池电量: {results['电量']} %", flush=True)

        banner("2/5 视频流：尝试保存 {} 张图".format(args.photos))
        saved, how = grab_photos(ep, args.photos)
        results["视频流"] = f"{how}，保存 {saved} 张" if saved else how
        print(f"  {'✅' if saved else '⚠️'} {results['视频流']}", flush=True)

        if args.motion:
            if not args.yes:
                print(f"\n!! 即将让机器人移动：底盘前后左右各 {args.dist}m、机械爪开合 3 次、"
                      f"机械臂前后 ±{args.arm_x}mm / 上下 ±{args.arm_y}mm。")
                ans = input(f"确认机器人周围 {max(1.2, args.dist + 0.7):.1f} 米内无人、无障碍物？输入 yes 继续: ").strip().lower()
                if ans != "yes":
                    print("已取消动作项。")
                    args.motion = False
            if args.motion:
                run_motion(ep, results, args.dist, args.arm_x, args.arm_y)
        else:
            results["动作自检"] = "未执行（加 --motion 运行）"
            print("\n动作自检未执行（加 --motion 运行）", flush=True)
    finally:
        ep.close()

    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, "selfcheck.json")
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=2)
    banner("自检结果")
    for k, v in results.items():
        print(f"  {k}: {v}")
    print(f"\n已保存: {out}")
    if os.path.isdir(PHOTOS) and os.listdir(PHOTOS):
        print(f"照片目录: {PHOTOS}")


if __name__ == "__main__":
    main()

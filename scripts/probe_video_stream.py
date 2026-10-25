#!/usr/bin/env python3
"""探测 EP 视频流（TCP 40921）的封装格式，并尝试用 PyAV 解码存图。

流程：SDK 连接 → 发命令开启图传 → 直连 40921 抓包 → 分析 H.264 起始码 → 尝试解码。
用法: ep38/bin/python scripts/probe_video_stream.py [--sec 4]
"""
import argparse
import os
import socket
import time

import av

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "results", "selfcheck_photos")
RAW = "/tmp/ep_stream_raw.bin"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=4.0)
    args = ap.parse_args()

    from robomaster import robot

    ep = robot.Robot()
    raw = b""
    try:
        ep.initialize(conn_type="sta")
        ip = ep.robot_ip if hasattr(ep, "robot_ip") else None
        if not ip:
            # 从连接对象里拿机器人 IP
            ip = ep.camera.video_stream_addr[0]
        print("机器人 IP:", ip, flush=True)

        print("开启图传命令 stream_sdk(1)...", flush=True)
        r1 = ep.camera._stream_sdk(1, "360p")
        print("  ->", r1, flush=True)
        print("开启图传命令 video_stream(1)...", flush=True)
        r2 = ep.camera._video_stream(1, "360p")
        print("  ->", r2, flush=True)
        time.sleep(0.5)

        print("直连视频端口 40921 抓包...", flush=True)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, 40921))
        t0 = time.time()
        while time.time() - t0 < args.sec:
            try:
                buf = s.recv(65536)
                if not buf:
                    break
                raw += buf
            except socket.timeout:
                print("  读超时（可能没在推流）", flush=True)
                break
        s.close()
        print(f"共收到 {len(raw)} 字节", flush=True)
        open(RAW, "wb").write(raw)

        n4 = raw.count(b"\x00\x00\x00\x01")
        n3 = raw.count(b"\x00\x00\x01")
        print(f"H.264 起始码: 4字节={n4} 3字节={n3}", flush=True)
        print("前 48 字节:", raw[:48].hex(" "), flush=True)

        # 尝试直接按 Annex-B 解码
        if n4 or n3:
            os.makedirs(OUT, exist_ok=True)
            ctx = av.CodecContext.create("h264", "r")
            saved = 0
            for pkt in ctx.parse(raw):
                for frame in ctx.decode(pkt):
                    img = frame.to_ndarray(format="bgr24")
                    import cv2
                    if saved == 0:
                        print("  解码到帧尺寸:", img.shape, flush=True)
                    cv2.imwrite(os.path.join(OUT, f"probe_{saved:02d}.jpg"), img)
                    saved += 1
                    if saved >= 12:
                        break
                if saved >= 12:
                    break
            print(f"✅ 解码成功，保存 {saved} 帧 -> {OUT}", flush=True)
        else:
            print("⚠️ 未发现标准 H.264 起始码，可能是私有封装；保存原始数据供分析", flush=True)
    finally:
        try:
            ep.camera._video_stream(0, "360p")
        except Exception:
            pass
        try:
            ep.camera._stream_sdk(0, "360p")
        except Exception:
            pass
        ep.close()


if __name__ == "__main__":
    main()

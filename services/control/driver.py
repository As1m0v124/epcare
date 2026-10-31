"""机器人控制服务：驱动层（真机 / 回放）+ 安全约束。

真机模式: 官方 SDK（Python 3.8 env `ep38`），视频流走 TCP 40921 裸 H.264 解码。
回放模式: 循环播放已采集的 EP 实拍帧（开发/演示用，状态标注 replay，不算真机数据）。
"""
import glob
import json
import os
import socket
import threading
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PHOTOS = sorted(glob.glob(os.path.join(ROOT, "results", "selfcheck_photos", "photo_*.jpg")))
AUDIT = os.path.join(ROOT, "logs", "control_audit.jsonl")
os.makedirs(os.path.dirname(AUDIT), exist_ok=True)


def audit(event, **kw):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **kw}
    with open(AUDIT, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class BaseDriver:
    mode = "base"

    def connect(self):
        raise NotImplementedError

    def close(self):
        pass

    def state(self):
        return {"mode": self.mode, "connected": False}

    def frame_jpeg(self):
        return None

    def move(self, x, y, z):
        raise NotImplementedError

    def stop(self):
        pass

    def grab(self, action):
        raise NotImplementedError

    def arm_move(self, x_mm, y_mm):
        raise NotImplementedError


class ReplayDriver(BaseDriver):
    """开发用回放：循环展示历史实拍帧，动作只记录日志（明确标注 replay）。"""

    mode = "replay"

    def __init__(self):
        self.connected = False
        self._idx = 0
        self._frames = []
        self._thread = None
        self._running = False
        self.last_cmd = None

    def connect(self):
        self._frames = [cv2.imread(p) for p in PHOTOS if cv2.imread(p) is not None]
        self.connected = True
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        audit("connect", mode="replay", frames=len(self._frames))
        return True

    def _loop(self):
        while self._running:
            time.sleep(0.4)

    def close(self):
        self._running = False
        self.connected = False

    def state(self):
        return {"mode": "replay", "connected": self.connected, "frames": len(self._frames),
                "last_cmd": self.last_cmd}

    def frame_jpeg(self):
        if not self._frames:
            return None
        self._idx = (self._idx + 1) % len(self._frames)
        ok, buf = cv2.imencode(".jpg", self._frames[self._idx])
        return buf.tobytes() if ok else None

    def move(self, x, y, z):
        self.last_cmd = {"move": [x, y, z], "ts": time.time()}
        audit("move", mode="replay", x=x, y=y, z=z)
        return True

    def stop(self):
        self.last_cmd = {"stop": True, "ts": time.time()}
        audit("stop", mode="replay")

    def grab(self, action):
        self.last_cmd = {"grab": action, "ts": time.time()}
        audit("grab", mode="replay", action=action)
        return True

    def arm_move(self, x_mm, y_mm):
        self.last_cmd = {"arm": [x_mm, y_mm], "ts": time.time()}
        audit("arm", mode="replay", x=x_mm, y=y_mm)
        return True


class RealEPDriver(BaseDriver):
    """真机驱动：SDK 控制 + TCP 40921 视频流解码。"""

    mode = "real"

    def __init__(self):
        self.ep = None
        self.connected = False
        self.last_error = ""
        self._frame = None
        self._video_thread = None
        self._running = False
        self._battery = None
        self._arm_pos = None
        self._lock = threading.Lock()

    # ---------- 连接 ----------
    def connect(self):
        from robomaster import robot

        self.ep = robot.Robot()
        self.ep.initialize(conn_type=os.environ.get("EP_CONN", "sta"))
        self.connected = True
        audit("connect", mode="real", version=self.ep.get_version(), sn=self.ep.get_sn())
        self._start_video()
        self._sub_battery()
        self._sub_arm()
        return True

    def _start_video(self):
        try:
            self.ep.camera._stream_sdk(1, "360p")
            self.ep.camera._video_stream(1, "360p")
            ip, port = self.ep.camera.video_stream_addr
            self._running = True
            self._video_thread = threading.Thread(target=self._video_loop, args=(ip, port), daemon=True)
            self._video_thread.start()
        except Exception as e:
            self.last_error = f"video start failed: {e!r}"
            audit("video_error", error=self.last_error)

    def _video_loop(self, ip, port):
        import av

        while self._running:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((ip, port))
                ctx = av.CodecContext.create("h264", "r")
                raw = b""
                while self._running:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                    if len(raw) > 200_000:
                        for pkt in ctx.parse(raw):
                            for frame in ctx.decode(pkt):
                                img = frame.to_ndarray(format="bgr24")
                                self._frame = img
                        raw = b""
            except Exception as e:
                self.last_error = f"video loop: {e!r}"
                time.sleep(1)

    def _sub_arm(self):
        try:
            self.ep.robotic_arm.sub_position(
                freq=5, callback=lambda pos: setattr(self, "_arm_pos", pos))
        except Exception:
            pass

    def _sub_battery(self):
        try:
            self.ep.battery.sub_battery_info(
                freq=1, callback=lambda p: setattr(self, "_battery", p))
        except Exception:
            pass

    def close(self):
        self._running = False
        try:
            self.ep.camera._video_stream(0, "360p")
            self.ep.camera._stream_sdk(0, "360p")
        except Exception:
            pass
        try:
            self.ep.close()
        except Exception:
            pass
        self.connected = False

    def battery(self):
        if self._battery is None:
            return None
        return int(self._battery)

    # ---------- 状态 ----------
    def state(self):
        return {"mode": "real", "connected": self.connected, "battery": self.battery(),
                "arm_pos": self._arm_pos, "last_error": self.last_error}

    def frame_jpeg(self):
        if self._frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", self._frame)
        return buf.tobytes() if ok else None

    # ---------- 动作 ----------
    def move(self, x, y, z):
        audit("move", mode="real", x=x, y=y, z=z)
        with self._lock:
            self.ep.chassis.move(x=x, y=y, z=z, xy_speed=0.5).wait_for_completed(timeout=30)
        return True

    def stop(self):
        audit("stop", mode="real")
        try:
            self.ep.chassis.stop()
        except Exception:
            pass

    def grab(self, action):
        audit("grab", mode="real", action=action)
        with self._lock:
            if action == "open":
                self.ep.gripper.open(power=50)
            else:
                self.ep.gripper.close(power=50)
        time.sleep(1.0)
        return True

    def arm_move(self, x_mm, y_mm):
        audit("arm", mode="real", x=x_mm, y=y_mm)
        with self._lock:
            self.ep.robotic_arm.move(x=x_mm, y=y_mm).wait_for_completed(timeout=15)
        return True

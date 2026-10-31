"""机器人控制服务 API（:8001）。只做机器人的事：连接、动作、急停、状态、视频帧。

安全约束（服务端强制执行，前端绕不过去）：
- 急停后拒绝一切动作，直到 clear_estop；
- 底盘距离与速度限幅（MAX_MOVE / SPEED_LIMIT）；
- 电量低于 15% 拒绝动作（真机模式）；
- 机械臂单次位移限幅 ±60mm；
- 每个动作写审计日志 logs/control_audit.jsonl。

启动（ep38 环境）:
  ep38/bin/python -m uvicorn services.control.server:app --host 127.0.0.1 --port 8001
"""
import os

from typing import Optional

import time

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .driver import ReplayDriver, RealEPDriver, audit

SPEED_LIMIT = float(os.environ.get("SPEED_LIMIT", "0.6"))   # m/s
MAX_MOVE = float(os.environ.get("MAX_MOVE", "1.0"))          # m（单次）
ARM_LIMIT_MM = int(os.environ.get("ARM_LIMIT_MM", "60"))     # mm（单次）
BATTERY_FLOOR = int(os.environ.get("BATTERY_FLOOR", "15"))   # %

app = FastAPI(title="EPCare Control Service")

_state = {"driver": None, "estop": False, "speed_limit": SPEED_LIMIT,
          "max_move": MAX_MOVE, "arm_limit_mm": ARM_LIMIT_MM, "events": 0}


def driver():
    return _state["driver"]


def require_driver():
    d = driver()
    if d is None or not d.connected:
        raise HTTPException(409, "机器人未连接（先 POST /connect）")
    return d


def guard_motion(d):
    if _state["estop"]:
        audit("reject", reason="estop")
        raise HTTPException(423, "急停中：请先解除急停")
    if d.mode == "real":
        b = d.battery()
        if b is not None and b < BATTERY_FLOOR:
            audit("reject", reason="low_battery", battery=b)
            raise HTTPException(409, f"电量过低（{b}% < {BATTERY_FLOOR}%），已拒绝动作")


class ConnectReq(BaseModel):
    mode: str = "replay"  # replay | real


class MoveReq(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    wait: bool = True


class GrabReq(BaseModel):
    action: str = "open"


class ArmReq(BaseModel):
    x_mm: float = 0.0
    y_mm: float = 0.0


class LimitsReq(BaseModel):
    speed_limit: Optional[float] = None
    max_move: Optional[float] = None
    arm_limit_mm: Optional[int] = None


@app.get("/health")
def health():
    return {"ok": True, "service": "control"}


@app.get("/state")
def state():
    d = driver()
    st = {"connected": False, "mode": None, "estop": _state["estop"],
          "speed_limit": _state["speed_limit"], "max_move": _state["max_move"],
          "arm_limit_mm": _state["arm_limit_mm"]}
    if d:
        st.update(d.state() if d.connected else {"mode": d.mode, "connected": d.connected})
    return st


@app.post("/connect")
def connect(req: ConnectReq):
    d = driver()
    if d:
        d.close()
    if req.mode == "real":
        d = RealEPDriver()
    elif req.mode == "replay":
        d = ReplayDriver()
    else:
        raise HTTPException(400, "mode 只能是 real 或 replay")
    try:
        d.connect()
    except Exception as e:
        raise HTTPException(502, f"连接失败: {e!r}")
    _state["driver"] = d
    audit("connect_ok", mode=req.mode)
    return {"ok": True, "mode": req.mode}


@app.post("/disconnect")
def disconnect():
    d = driver()
    if d:
        d.close()
    _state["driver"] = None
    return {"ok": True}


@app.post("/estop")
def estop():
    _state["estop"] = True
    d = driver()
    if d and d.connected:
        d.stop()
    audit("estop")
    return {"ok": True, "estop": True}


@app.post("/clear-estop")
def clear_estop():
    _state["estop"] = False
    audit("clear_estop")
    return {"ok": True, "estop": False}


@app.post("/move")
def move(req: MoveReq):
    d = require_driver()
    guard_motion(d)
    for v in (req.x, req.y):
        if abs(v) > _state["max_move"]:
            raise HTTPException(400, f"单次位移超限（|{v}| > {_state['max_move']} m）")
    if abs(req.z) > 180:
        raise HTTPException(400, "单次旋转超限（>180°）")
    try:
        d.move(req.x, req.y, req.z, wait=req.wait)
    except Exception as e:
        audit("move_error", error=repr(e))
        raise HTTPException(500, f"动作失败: {e!r}")
    return {"ok": True}


@app.post("/stop")
def stop():
    d = driver()
    if d and d.connected:
        d.stop()
    audit("stop_api")
    return {"ok": True}


@app.post("/grab")
def grab(req: GrabReq):
    d = require_driver()
    guard_motion(d)
    if req.action not in ("open", "close"):
        raise HTTPException(400, "action 只能是 open/close")
    d.grab(req.action)
    return {"ok": True}


@app.post("/arm")
def arm(req: ArmReq):
    d = require_driver()
    guard_motion(d)
    if abs(req.x_mm) > _state["arm_limit_mm"] or abs(req.y_mm) > _state["arm_limit_mm"]:
        raise HTTPException(400, f"机械臂单次位移超限（>{_state['arm_limit_mm']}mm）")
    d.arm_move(req.x_mm, req.y_mm)
    return {"ok": True}


@app.post("/limits")
def set_limits(req: LimitsReq):
    if req.speed_limit is not None:
        _state["speed_limit"] = max(0.1, min(1.5, req.speed_limit))
    if req.max_move is not None:
        _state["max_move"] = max(0.1, min(2.0, req.max_move))
    if req.arm_limit_mm is not None:
        _state["arm_limit_mm"] = max(10, min(150, req.arm_limit_mm))
    audit("set_limits", **{k: v for k, v in _state.items() if k != "driver"})
    return {"ok": True, **{k: _state[k] for k in ("speed_limit", "max_move", "arm_limit_mm")}}


@app.get("/stream.mjpg")
def stream_mjpg():
    """低延迟 MJPEG 流（约 12 帧/秒），浏览器 <img> 直接播放。"""
    d = driver()
    if d is None:
        raise HTTPException(409, "未连接")

    def gen():
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
        while True:
            jpg = d.frame_jpeg()
            if jpg:
                yield boundary + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
            time.sleep(1 / 12)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/frame.jpg")
def frame():
    d = driver()
    if d is None:
        raise HTTPException(409, "未连接")
    jpg = d.frame_jpeg()
    if jpg is None:
        raise HTTPException(404, "暂无画面")
    return Response(content=jpg, media_type="image/jpeg")

"""EPCare 后端（:8000）：登录/权限、房间地标、巡检与找东西任务、告警、规则、评测、看板、审计。

机器人动作一切经过控制服务（:8001），后端不做 SDK 调用；安全约束由控制服务强制执行。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from . import db, ml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
CONTROL = os.environ.get("CONTROL_URL", "http://127.0.0.1:8001")
SECRET_FILE = os.path.join(ROOT, "db", "secret")
os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
if not os.path.exists(SECRET_FILE):
    open(SECRET_FILE, "w").write(os.urandom(32).hex())
SECRET = open(SECRET_FILE).read().strip().encode()

ROLE_ORDER = {"family": 1, "caregiver": 2, "admin": 3}
ZH2EN = {
    "拖鞋": "slippers", "纸箱": "cardboard box", "盒子": "box", "椅子": "chair",
    "水瓶": "water bottle", "水杯": "cup", "电线": "cable", "药盒": "pill box",
    "眼镜": "glasses", "遥控器": "remote control", "袜子": "socks", "玩具": "toy",
    "书": "book", "包": "bag", "手机": "cell phone",
}

app = FastAPI(title="EPCare Backend")


def sign(payload: bytes) -> str:
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()


def make_session(user):
    data = json.dumps({"u": user["username"], "r": user["role"], "t": int(time.time())}).encode()
    return base64.urlsafe_b64encode(data).decode() + "." + sign(data)


def read_session(request: Request):
    raw = request.cookies.get("epcare_session")
    if not raw or "." not in raw:
        return None
    b64, sig = raw.rsplit(".", 1)
    try:
        data = base64.urlsafe_b64decode(b64.encode())
    except Exception:
        return None
    if not hmac.compare_digest(sign(data), sig):
        return None
    d = json.loads(data)
    if time.time() - d.get("t", 0) > 7 * 86400:
        return None
    return {"username": d["u"], "role": d["r"]}


def require(request: Request, min_role="family"):
    user = read_session(request)
    if not user:
        raise HTTPException(401, "未登录")
    if ROLE_ORDER[user["role"]] < ROLE_ORDER[min_role]:
        raise HTTPException(403, "权限不足")
    return user


def ctrl(path, method="GET", body=None):
    url = CONTROL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(), r.headers.get("Content-Type", "application/json"), r.status
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")
        raise HTTPException(e.code, f"控制服务: {detail}")
    except Exception as e:
        raise HTTPException(503, f"控制服务不可用: {e!r}")


def ctrl_json(path, method="GET", body=None):
    raw, _, _ = ctrl(path, method, body)
    return json.loads(raw)


@app.on_event("startup")
def startup():
    db.init()


# ---------------- 认证 ----------------
@app.post("/api/login")
def login(resp: Response, username: str = Body(...), password: str = Body(...)):
    u = db.check_user(username, password)
    if not u:
        raise HTTPException(401, "用户名或密码错误")
    resp.set_cookie("epcare_session", make_session(u), httponly=True, samesite="lax", max_age=7 * 86400)
    db.audit(u["username"], "login")
    return {"ok": True, "username": u["username"], "role": u["role"]}


@app.post("/api/logout")
def logout(request: Request, resp: Response):
    u = read_session(request)
    if u:
        db.audit(u["username"], "logout")
    resp.delete_cookie("epcare_session")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    return require(request)


# ---------------- 控制服务代理 ----------------
@app.get("/api/control/state")
def control_state(request: Request):
    require(request)
    return ctrl_json("/state")


@app.get("/api/control/frame.jpg")
def control_frame(request: Request):
    require(request)
    raw, ctype, _ = ctrl("/frame.jpg")
    return Response(content=raw, media_type=ctype)


@app.post("/api/control/estop")
def control_estop(request: Request):
    require(request)  # 所有角色都可以急停
    db.audit(read_session(request)["username"], "estop")
    return ctrl_json("/estop", "POST")


@app.post("/api/control/clear-estop")
def control_clear(request: Request):
    require(request, "admin")
    db.audit(read_session(request)["username"], "clear_estop")
    return ctrl_json("/clear-estop", "POST")


@app.post("/api/control/move")
def control_move(request: Request, payload: dict = Body(...)):
    u = require(request, "caregiver")
    db.audit(u["username"], "move", json.dumps(payload, ensure_ascii=False))
    return ctrl_json("/move", "POST", payload)


@app.post("/api/control/stop")
def control_stop(request: Request):
    u = require(request)
    db.audit(u["username"], "stop")
    return ctrl_json("/stop", "POST")


@app.post("/api/control/grab")
def control_grab(request: Request, payload: dict = Body(...)):
    u = require(request, "caregiver")
    db.audit(u["username"], "grab", json.dumps(payload))
    return ctrl_json("/grab", "POST", payload)


@app.post("/api/control/arm")
def control_arm(request: Request, payload: dict = Body(...)):
    u = require(request, "caregiver")
    db.audit(u["username"], "arm", json.dumps(payload))
    return ctrl_json("/arm", "POST", payload)


@app.post("/api/control/connect")
def control_connect(request: Request, payload: dict = Body(...)):
    u = require(request, "admin")
    db.audit(u["username"], "connect", payload.get("mode", ""))
    return ctrl_json("/connect", "POST", payload)


@app.post("/api/control/disconnect")
def control_disconnect(request: Request):
    u = require(request, "admin")
    db.audit(u["username"], "disconnect")
    return ctrl_json("/disconnect", "POST")


@app.post("/api/control/limits")
def control_limits(request: Request, payload: dict = Body(...)):
    u = require(request, "admin")
    db.audit(u["username"], "set_limits", json.dumps(payload))
    return ctrl_json("/limits", "POST", payload)


# ---------------- 视觉（F1/F2） ----------------
def latest_frame():
    raw, _, _ = ctrl("/frame.jpg")
    return raw


@app.get("/api/depth.jpg")
def depth_image(request: Request):
    require(request)
    jpg = latest_frame()
    png, _ = ml.depth_map(jpg)
    if png is None:
        raise HTTPException(500, "深度图生成失败")
    return Response(content=png, media_type="image/png")


@app.post("/api/detect")
def detect(request: Request, payload: dict = Body(...)):
    u = require(request)
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    words = [w for w in query.replace("，", " ").replace("、", " ").split() if w]
    en = [ZH2EN.get(w, w) for w in words]
    text = " . ".join(en) + " ."
    jpg = latest_frame()
    items = ml.detect(jpg, text)
    db.audit(u["username"], "detect", f"{query} -> {text}")
    return {"query": query, "prompt": text, "items": items, "count": len(items)}


# ---------------- 房间 / 地标 ----------------
@app.get("/api/rooms")
def rooms(request: Request):
    require(request)
    with db.conn() as c:
        rms = [dict(r) for r in c.execute("SELECT * FROM rooms ORDER BY id")]
        for r in rms:
            r["landmarks"] = [dict(x) for x in c.execute(
                "SELECT * FROM landmarks WHERE room_id=? ORDER BY id", (r["id"],))]
    return rms


@app.post("/api/rooms")
def add_room(request: Request, payload: dict = Body(...)):
    u = require(request, "admin")
    with db.conn() as c:
        try:
            cur = c.execute("INSERT INTO rooms(name, note, created) VALUES(?,?,?)",
                            (payload["name"], payload.get("note", ""), db.now()))
        except Exception:
            raise HTTPException(400, "房间已存在")
    db.audit(u["username"], "add_room", payload["name"])
    return {"id": cur.lastrowid}


@app.post("/api/rooms/{room_id}/landmarks")
def add_landmark(request: Request, room_id: int, payload: dict = Body(...)):
    u = require(request, "admin")
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO landmarks(room_id, name, tag_id, x, y, created) VALUES(?,?,?,?,?,?)",
            (room_id, payload["name"], payload.get("tag_id", ""),
             float(payload.get("x", 0)), float(payload.get("y", 0)), db.now()))
    db.audit(u["username"], "add_landmark", payload["name"])
    return {"id": cur.lastrowid}


# ---------------- 任务 ----------------
@app.get("/api/tasks")
def list_tasks(request: Request):
    require(request)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 50")]


@app.post("/api/tasks/find")
def task_find(request: Request, payload: dict = Body(...)):
    u = require(request)
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    words = [w for w in query.replace("，", " ").replace("、", " ").split() if w]
    text = " . ".join(ZH2EN.get(w, w) for w in words) + " ."
    jpg = latest_frame()
    items = ml.detect(jpg, text)
    # 存一张标注截图
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    for it in items[:5]:
        x1, y1, x2, y2 = [int(v) for v in it["box"]]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
    shot_dir = os.path.join(ROOT, "results", "find")
    os.makedirs(shot_dir, exist_ok=True)
    shot = os.path.join(shot_dir, f"find_{int(time.time())}.jpg")
    cv2.imwrite(shot, img)
    status = "found" if items else "not_found"
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO tasks(kind, payload, status, result, created_by, created, finished) "
            "VALUES(?,?,?,?,?,?,?)",
            ("find", json.dumps({"query": query, "prompt": text}, ensure_ascii=False),
             status, json.dumps({"items": items[:20], "shot": os.path.relpath(shot, ROOT)},
                                ensure_ascii=False), u["username"], db.now(), db.now()))
    db.audit(u["username"], "find", f"{query} -> {len(items)} 个")
    return {"task_id": cur.lastrowid, "query": query, "items": items,
            "count": len(items), "status": status}


@app.post("/api/tasks/{task_id}/run")
def run_task(request: Request, task_id: int, payload: dict | None = Body(default=None)):
    """执行巡检计划：replay 模式逐步发送移动指令（仅演练）；真机模式暂未开放。"""
    u = require(request, "caregiver")
    with db.conn() as c:
        task = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["kind"] != "patrol":
        raise HTTPException(400, "只有巡检任务可以执行")
    if task["status"] not in ("planned", "finished"):
        raise HTTPException(409, "任务状态不允许执行")
    st = ctrl_json("/state")
    confirm = bool(payload.get("confirm_real")) if isinstance(payload, dict) else False
    if st.get("mode") != "replay":
        if not confirm:
            raise HTTPException(409, "真机执行需现场确认：请传 confirm_real=true（确保周围 1.5m 无障碍）")
        if st.get("battery") is not None and st["battery"] < 25:
            raise HTTPException(409, f"电量过低（{st['battery']}%），拒绝真机执行")
    plan = json.loads(task["payload"]).get("plan", [])
    steps, started = [], db.now()
    with db.conn() as c:
        c.execute("UPDATE tasks SET status='running' WHERE id=?", (task_id,))
    for name in plan:
        st = ctrl_json("/state")
        if st.get("estop"):
            steps.append({"landmark": name, "result": "aborted: estop"})
            break
        dist = 0.2
        ctrl_json("/move", "POST", {"x": dist, "y": 0.0, "z": 0.0})
        steps.append({"landmark": name, "result": f"{st.get('mode')} move {dist}m"})
    status = "finished"
    with db.conn() as c:
        c.execute("UPDATE tasks SET status=?, result=?, finished=? WHERE id=?",
                  (status, json.dumps({"steps": steps, "note": "replay 演练，未真实移动"},
                                      ensure_ascii=False), db.now(), task_id))
    db.audit(u["username"], "patrol_run", f"task {task_id}: {len(steps)} 步")
    return {"ok": True, "task_id": task_id, "steps": steps, "status": status}


@app.post("/api/tasks/fetch")
def task_fetch(request: Request, payload: dict = Body(...)):
    """找东西→取回（replay 演示动作序列：对准→伸臂→夹取→回收）。真机暂未开放。"""
    u = require(request, "caregiver")
    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "query 不能为空")
    st = ctrl_json("/state")
    if st.get("mode") != "replay" and not payload.get("confirm_real"):
        raise HTTPException(409, "真机取回需现场确认：请传 confirm_real=true")
    steps = []
    for ep, act in [("/arm", {"x_mm": 20, "y_mm": 0}), ("/grab", {"action": "open"}),
                    ("/arm", {"x_mm": 10, "y_mm": -5}), ("/grab", {"action": "close"}),
                    ("/arm", {"x_mm": -20, "y_mm": 0})]:
        ctrl_json(ep, "POST", act)
        steps.append({"api": ep, **act})
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO tasks(kind, payload, status, result, created_by, created, finished) "
            "VALUES(?,?,?,?,?,?,?)",
            ("fetch", json.dumps({"query": query}, ensure_ascii=False), "finished",
             json.dumps({"steps": steps, "note": "replay 演示序列，未真实抓取"},
                        ensure_ascii=False), u["username"], db.now(), db.now()))
    db.audit(u["username"], "fetch", query)
    return {"ok": True, "task_id": cur.lastrowid, "query": query, "steps": steps}


@app.get("/api/tasks/{task_id}")
def get_task(request: Request, task_id: int):
    require(request)
    with db.conn() as c:
        r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not r:
        raise HTTPException(404, "任务不存在")
    return dict(r)


@app.post("/api/tasks/patrol")
def task_patrol(request: Request, payload: dict = Body(...)):
    """生成巡检计划（按地标最近邻排序）。replay 模式可演练，真机执行需现场确认（未启用）。"""
    u = require(request, "caregiver")
    room_id = int(payload.get("room_id", 0))
    with db.conn() as c:
        room = c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        lms = [dict(r) for r in c.execute(
            "SELECT * FROM landmarks WHERE room_id=? ORDER BY id", (room_id,))]
    if not room:
        raise HTTPException(404, "房间不存在")
    if not lms:
        raise HTTPException(400, "房间没有地标")
    # 最近邻顺序
    plan, cur, rest = [], lms[0], lms[1:]
    plan.append(cur["name"])
    while rest:
        nxt = min(rest, key=lambda m: (m["x"] - cur["x"]) ** 2 + (m["y"] - cur["y"]) ** 2)
        plan.append(nxt["name"])
        rest.remove(nxt)
        cur = nxt
    state = ctrl_json("/state") if payload.get("probe", True) else {}
    mode = state.get("mode")
    rehearsal = payload.get("rehearse") and mode == "replay"
    status = "finished" if rehearsal else "planned"
    result = {"room": room["name"], "plan": plan, "mode": mode,
              "note": "replay 演练：只记录流程，未真实移动" if rehearsal
              else "计划已生成；真机执行需现场确认（后续版本启用）"}
    with db.conn() as c:
        cur2 = c.execute(
            "INSERT INTO tasks(kind, payload, status, result, created_by, created, finished) "
            "VALUES(?,?,?,?,?,?,?)",
            ("patrol", json.dumps({"room_id": room_id, "plan": plan}, ensure_ascii=False),
             status, json.dumps(result, ensure_ascii=False), u["username"],
             db.now(), db.now() if rehearsal else None))
    db.audit(u["username"], "patrol_plan", json.dumps({"room": room["name"], "plan": plan},
                                                      ensure_ascii=False))
    return {"task_id": cur2.lastrowid, **result, "status": status}


# ---------------- 告警 ----------------
@app.get("/api/alerts")
def alerts(request: Request):
    require(request)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 100")]


@app.post("/api/alerts")
def add_alert(request: Request, payload: dict = Body(...)):
    u = require(request, "caregiver")
    try:
        jpg = latest_frame()
        shot_dir = os.path.join(ROOT, "results", "alerts")
        os.makedirs(shot_dir, exist_ok=True)
        photo = os.path.join(shot_dir, f"alert_{int(time.time())}.jpg")
        open(photo, "wb").write(jpg)
        photo_rel = os.path.relpath(photo, ROOT)
    except Exception:
        photo_rel = ""
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO alerts(room_id, kind, description, photo, status, created) "
            "VALUES(?,?,?,?,?,?)",
            (payload.get("room_id"), payload.get("kind", "other"),
             payload.get("description", ""), photo_rel, "open", db.now()))
    db.audit(u["username"], "add_alert", payload.get("kind", ""))
    return {"id": cur.lastrowid, "photo": photo_rel}


@app.post("/api/alerts/{alert_id}/resolve")
def resolve_alert(request: Request, alert_id: int):
    u = require(request, "caregiver")
    with db.conn() as c:
        c.execute("UPDATE alerts SET status='resolved', resolved_by=?, resolved_at=? WHERE id=?",
                  (u["username"], db.now(), alert_id))
    db.audit(u["username"], "resolve_alert", str(alert_id))
    return {"ok": True}


# ---------------- 收纳规则 ----------------
@app.get("/api/rules")
def get_rules(request: Request):
    require(request)
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM rules ORDER BY id DESC LIMIT 20")]


@app.post("/api/rules")
def add_rules(request: Request, payload: dict = Body(...)):
    u = require(request)
    examples_raw = payload.get("examples", [])
    pairs = []
    for line in examples_raw:
        if ":" in line:
            o, p = line.split(":", 1)
        elif "放" in line:
            o, p = line.split("放", 1)
        else:
            continue
        pairs.append((o.strip(), p.strip()))
    if len(pairs) < 2:
        raise HTTPException(400, "至少给两条示例（以冒号或“放”分隔，如 降压药:床头柜）")
    res = ml.tidy_rules(pairs)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO rules(household, examples, rules_text, created) VALUES(?,?,?,?)",
            (payload.get("household", "默认家庭"), json.dumps(examples_raw, ensure_ascii=False),
             res["rules"], db.now()))
    db.audit(u["username"], "tidy_rules", res.get("model", ""))
    return {"id": cur.lastrowid, "rules": res["rules"], "model": res.get("model", "")}


# ---------------- 评测 / 看板 / 设备 / 审计 ----------------
@app.get("/api/eval")
def eval_results(request: Request):
    require(request)
    res_dir = os.path.join(ROOT, "results")
    out = {}
    mapping = {
        "nyu_f1.json": "F1 NYU-D",
        "coco_f2.json": "F2 COCO(500)",
        "coco_f2_full.json": "F2 COCO(全量)",
        "tidybot_f3.json": "F3 TidyBot(20)",
        "tidybot_f3_96.json": "F3 TidyBot(96)",
        "tidybot_f3_40_zh.json": "F3 中文场景(40)",
        "da2k.json": "F1 DA-2K",
        "refcoco.json": "F2 RefCOCO",
    }
    for fn, name in mapping.items():
        p = os.path.join(res_dir, fn)
        if os.path.exists(p):
            out[name] = json.load(open(p))
    return out


@app.get("/api/dashboard")
def dashboard(request: Request):
    require(request)
    with db.conn() as c:
        tasks = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) n FROM tasks GROUP BY status")}
        alerts_open = c.execute("SELECT COUNT(*) n FROM alerts WHERE status='open'").fetchone()["n"]
        alerts_total = c.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
    try:
        st = ctrl_json("/state")
    except Exception:
        st = {"connected": False}
    return {"tasks": tasks, "alerts_open": alerts_open, "alerts_total": alerts_total,
            "robot": st}


@app.get("/api/audit")
def audit_log(request: Request):
    require(request)
    with db.conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")]
    ctrl_events = []
    p = os.path.join(ROOT, "logs", "control_audit.jsonl")
    if os.path.exists(p):
        ctrl_events = [json.loads(l) for l in open(p).read().strip().split("\n")[-50:] if l]
    return {"backend": rows, "control": ctrl_events}


# ---------------- 侧边栏助手（规则路由） ----------------
@app.get("/api/assistant")
def assistant(request: Request, q: str):
    require(request)
    q = q.strip()
    if not q:
        raise HTTPException(400, "q 不能为空")
    if any(k in q for k in ("找", "在哪", "快照")):
        return {"action": "find", "reply": "好的，我去找一下。", "query": q}
    if any(k in q for k in ("巡检", "巡视", "检查")):
        return {"action": "patrol", "reply": "可以，去「巡检任务」页选房间生成计划。"}
    if any(k in q for k in ("收纳", "放哪", "规则", "习惯")):
        return {"action": "rules", "reply": "去「家庭收纳习惯」录入示例，我来归纳。"}
    if any(k in q for k in ("电量", "状态", "连接")):
        try:
            st = ctrl_json("/state")
            return {"action": "status", "reply": f"机器人：{'已连接' if st.get('connected') else '未连接'}，"
                                                 f"模式 {st.get('mode')}，电量 {st.get('battery')}%，急停 {'开' if st.get('estop') else '关'}。"}
        except Exception as e:
            return {"action": "status", "reply": f"控制服务不可用：{e!r}"}
    return {"action": "help", "reply": "我可以帮你：找东西、生成巡检计划、归纳收纳规则、查机器人状态。"}


# ---------------- 静态前端 ----------------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/files/{path:path}")
def result_files(request: Request, path: str):
    require(request)
    base = os.path.abspath(os.path.join(ROOT, "results"))
    p = os.path.abspath(os.path.join(ROOT, path))
    if not p.startswith(base):
        raise HTTPException(403)
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/static/{path:path}")
def static_files(path: str):
    p = os.path.join(STATIC, path)
    if not os.path.abspath(p).startswith(os.path.abspath(STATIC)):
        raise HTTPException(403)
    return FileResponse(p)

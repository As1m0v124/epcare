"""SQLite 数据库：用户/房间/地标/任务/告警/规则/审计。"""
import hashlib
import json
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.environ.get("EPCARE_DB", os.path.join(ROOT, "db", "epcare.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, salt TEXT, pwd_hash TEXT,
  role TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS rooms(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS landmarks(
  id INTEGER PRIMARY KEY, room_id INTEGER, name TEXT, tag_id TEXT, x REAL, y REAL, created TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, status TEXT, result TEXT,
  created_by TEXT, created TEXT, finished TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY, room_id INTEGER, kind TEXT, description TEXT, photo TEXT,
  status TEXT, created TEXT, resolved_by TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY, household TEXT, examples TEXT, rules_text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts TEXT, user TEXT, action TEXT, detail TEXT);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def hash_pwd(salt, pwd):
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), bytes.fromhex(salt), 120_000).hex()


def add_user(username, pwd, role):
    salt = os.urandom(8).hex()
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO users(username, salt, pwd_hash, role, created) VALUES(?,?,?,?,?)",
                  (username, salt, hash_pwd(salt, pwd), role, now()))


def check_user(username, pwd):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not r:
        return None
    return dict(r) if hash_pwd(r["salt"], pwd) == r["pwd_hash"] else None


def audit(user, action, detail=""):
    with conn() as c:
        c.execute("INSERT INTO audit(ts, user, action, detail) VALUES(?,?,?,?)",
                  (now(), user, action, detail))


def init():
    with conn() as c:
        c.executescript(SCHEMA)
    add_user("admin", "admin123", "admin")
    add_user("caregiver1", "care123", "caregiver")
    add_user("family1", "family123", "family")
    with conn() as c:
        if c.execute("SELECT COUNT(*) n FROM rooms").fetchone()["n"] == 0:
            c.execute("INSERT INTO rooms(name, note, created) VALUES(?,?,?)",
                      ("客厅", "演示房间", now()))
            rid = c.execute("SELECT id FROM rooms WHERE name='客厅'").fetchone()["id"]
            for i, (name, tag) in enumerate([("沙发", "TAG-SOFA"), ("电视柜", "TAG-TV"), ("门口", "TAG-DOOR")]):
                c.execute("INSERT INTO landmarks(room_id, name, tag_id, x, y, created) VALUES(?,?,?,?,?,?)",
                          (rid, name, tag, i * 1.5, 0.0, now()))


if __name__ == "__main__":
    init()
    print("初始化完成:", DB_PATH)

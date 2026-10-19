"""Durable integer task IDs, idempotency and one active editor binding."""
import json
import fcntl
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .protocol import digest

STATES = ("已创建", "已进入队列", "进行中", "任务完成", "任务失败")


class TaskStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.process_lock = open(str(path) + ".lock", "a+")
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.process_lock.close()
            raise ValueError("agent_service_already_running") from None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, browser TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 0, uncertain INTEGER NOT NULL DEFAULT 0);
        CREATE UNIQUE INDEX IF NOT EXISTS single_active ON sessions(active) WHERE active=1;
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
          request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
          result TEXT, created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(session,request_key));
        """)
        with self.lock, self.db:
            self.db.execute("UPDATE sessions SET uncertain=1 WHERE id IN (SELECT session FROM tasks WHERE state='进行中')")
            self.db.execute("UPDATE tasks SET state='任务失败', result=?, updated=? WHERE state IN ('已创建','已进入队列','进行中')",
                (json.dumps({"outcome": "failed", "executed": False, "error": {"code": "service_restarted", "message": "Interrupted; do not replay automatically"}}), time.time()))

    def busy(self):
        return self.db.execute("SELECT 1 FROM tasks WHERE state IN ('已创建','已进入队列','进行中') LIMIT 1").fetchone() is not None

    def activate(self, browser, session=None):
        with self.lock, self.db:
            if self.busy():
                raise ValueError("task_busy")
            if session is not None:
                row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
                if row is None:
                    raise ValueError("session_not_found")
                if row["uncertain"]:
                    raise ValueError("session_reconciliation_required")
            else:
                session = uuid.uuid4().hex
                self.db.execute("INSERT INTO sessions(id,browser) VALUES (?,?)", (session,browser))
            self.db.execute("UPDATE sessions SET active=0")
            self.db.execute("UPDATE sessions SET active=1,browser=? WHERE id=?", (browser, session))
        return session

    def binding(self, session):
        with self.lock:
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
            if row is None:
                raise ValueError("session_not_found")
            return dict(row)

    def sessions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM sessions")]

    def submit(self, task):
        value = task.model_dump(mode="json")
        fingerprint = digest(value)
        with self.lock, self.db:
            existing = self.db.execute("SELECT * FROM tasks WHERE session=? AND request_key=?", (task.sessionID,task.clientRequestID)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("idempotency_conflict")
                return self.get(existing["id"]), False
            binding = self.binding(task.sessionID)
            if not binding["active"] or binding["browser"] != task.browserID:
                raise ValueError("session_browser_not_active")
            if binding["uncertain"]:
                raise ValueError("session_reconciliation_required")
            if self.busy():
                raise ValueError("task_busy")
            now = time.time()
            cursor = self.db.execute("INSERT INTO tasks(session,request_key,fingerprint,payload,state,created,updated) VALUES (?,?,?,?,?,?,?)",
                (task.sessionID,task.clientRequestID,fingerprint,json.dumps(value,ensure_ascii=False),"已创建",now,now))
            return self.get(cursor.lastrowid), True

    def get(self, identifier):
        with self.lock:
            row = self.db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("task_not_found")
            data = dict(row)
            data["payload"] = json.loads(data["payload"])
            data["result"] = json.loads(data["result"]) if data["result"] else None
            return data

    def update(self, identifier, state, result=None, *, uncertain=False):
        if state not in STATES:
            raise ValueError("invalid_task_state")
        with self.lock, self.db:
            self.db.execute("UPDATE tasks SET state=?,result=?,updated=? WHERE id=?", (state,
                json.dumps(result,ensure_ascii=False,allow_nan=False) if result is not None else None,time.time(),identifier))
            if uncertain:
                self.db.execute("UPDATE sessions SET uncertain=1 WHERE id=(SELECT session FROM tasks WHERE id=?)", (identifier,))

    def close(self):
        self.db.close()
        self.process_lock.close()

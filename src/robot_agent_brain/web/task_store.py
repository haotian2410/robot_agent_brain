"""Durable integer task IDs, idempotency and one active editor binding."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from ..filelock import lock_exclusive
from .protocol import digest

DEFAULT_STATES = ("已创建", "已进入队列", "进行中", "任务完成", "任务失败")


class TaskStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.process_lock = open(str(path) + ".lock", "a+b")
        try:
            lock_exclusive(self.process_lock.fileno())
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
          result TEXT, terminal INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
          UNIQUE(session,request_key));
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(tasks)")}
        if "terminal" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN terminal INTEGER NOT NULL DEFAULT 0")
        with self.lock, self.db:
            self.db.execute("UPDATE sessions SET uncertain=1 WHERE id IN (SELECT session FROM tasks WHERE terminal=0)")
            self.db.execute("UPDATE tasks SET state='service_restarted', terminal=1, result=?, updated=? WHERE terminal=0",
                (json.dumps({"outcome": "failed", "executed": False, "error": {"code": "service_restarted", "message": "Interrupted; do not replay automatically"}}), time.time()))

    def busy(self):
        return self.db.execute("SELECT 1 FROM tasks WHERE terminal=0 LIMIT 1").fetchone() is not None

    def activate(self, browser, session=None, *, allow_active_task=False):
        with self.lock, self.db:
            if self.busy() and not allow_active_task:
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
        # Keep the submitted Scene document lossless. Pydantic materializes the optional
        # scene_sub_version=0 when serializing a nested SceneConfig, which changes the JCS digest
        # before the worker re-reads the durable task and makes a valid browser snapshot look
        # like a gateway scene conflict.
        if hasattr(task.scene, "raw_document") and "scene_sub_version" not in task.scene.raw_document():
            value["scene"].pop("scene_sub_version", None)
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
            # The browser may switch to another session while an older session's task is still
            # running.  Keep the one-running-task rule per session, but allow a different session
            # to queue behind the single worker; its scene/lease is isolated by the Gateway.
            same_session_busy = self.db.execute(
                "SELECT 1 FROM tasks WHERE terminal=0 AND session=? LIMIT 1", (task.sessionID,)
            ).fetchone() is not None
            if same_session_busy:
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
            data["terminal"] = bool(data["terminal"])
            data["payload"] = json.loads(data["payload"])
            data["result"] = json.loads(data["result"]) if data["result"] else None
            return data

    def update(self, identifier, state, result=None, *, uncertain=False, terminal=None):
        if not isinstance(state, str) or not state.strip():
            raise ValueError("invalid_task_state")
        if terminal is None:
            terminal = result is not None and isinstance(result, dict) and result.get("outcome") is not None
        with self.lock, self.db:
            self.db.execute("UPDATE tasks SET state=?,result=?,terminal=?,updated=? WHERE id=?", (state,
                json.dumps(result,ensure_ascii=False,allow_nan=False) if result is not None else None,
                int(bool(terminal)), time.time(), identifier))
            if uncertain:
                self.db.execute("UPDATE sessions SET uncertain=1 WHERE id=(SELECT session FROM tasks WHERE id=?)", (identifier,))

    def close(self):
        self.db.close()
        self.process_lock.close()

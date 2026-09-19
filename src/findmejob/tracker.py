"""Local SQLite tracker: jobs, events, pending questions, learned preferences."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import JobPosting

STATUSES = [
    "new", "shortlisted", "blocked", "needs_input", "tailored", "ready",
    "applied", "skipped", "rejected",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new',
  score INTEGER,
  policy_verdict TEXT,
  notes TEXT DEFAULT '',
  first_seen REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  ts REAL NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pending (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  question TEXT NOT NULL,
  asked REAL NOT NULL,
  answer TEXT,
  answered REAL
);
CREATE TABLE IF NOT EXISTS prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0,
  result TEXT DEFAULT '',
  created REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS company_verifications (
  job_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL
);
"""


class _LockedConn:
    """Thread-safe wrapper so the web UI threads can share one connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def commit(self):
        with self._lock:
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()


FOLLOW_UP_DAYS = 7


class Tracker:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(self.db_path), check_same_thread=False)
        raw.row_factory = sqlite3.Row
        self.conn = _LockedConn(raw)
        self.conn.executescript(_SCHEMA)
        try:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN follow_up REAL")
            self.conn.commit()
        except Exception:
            pass  # column already exists

    def close(self) -> None:
        self.conn.close()

    # jobs
    def upsert_job(self, job: JobPosting, score: int | None = None,
                   verdict: str | None = None, status: str = "new") -> bool:
        now = time.time()
        row = self.conn.execute("SELECT id FROM jobs WHERE id=?", (job.id,)).fetchone()
        data = json.dumps(job.to_dict())
        if row:
            self.conn.execute(
                "UPDATE jobs SET data=?, score=COALESCE(?,score), policy_verdict=COALESCE(?,policy_verdict), updated=? WHERE id=?",
                (data, score, verdict, now, job.id))
            return False
        self.conn.execute(
            "INSERT INTO jobs (id,data,status,score,policy_verdict,first_seen,updated) VALUES (?,?,?,?,?,?,?)",
            (job.id, data, status, score, verdict, now, now))
        self.add_event(job.id, "found", f"{job.source}: {job.title} @ {job.company}")
        return True

    def get_job(self, job_id: str) -> JobPosting | None:
        row = self.conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return JobPosting.from_dict(json.loads(row["data"])) if row else None

    def find_jobs(self, query: str) -> list[sqlite3.Row]:
        like = f"%{query}%"
        return self.conn.execute(
            "SELECT * FROM jobs WHERE id=? OR data LIKE ? ORDER BY updated DESC LIMIT 10",
            (query, like)).fetchall()

    def resolve_job_id(self, query: str) -> str | None:
        rows = self.find_jobs(query)
        if not rows:
            return None
        exact = [r for r in rows if r["id"] == query]
        return (exact or rows)[0]["id"]

    def set_status(self, job_id: str, status: str, note: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status}")
        follow_up = time.time() + FOLLOW_UP_DAYS * 86400 if status == "applied" else None
        self.conn.execute(
            "UPDATE jobs SET status=?, notes=CASE WHEN ?='' THEN notes ELSE ? END, updated=?,"
            " follow_up=COALESCE(?, follow_up) WHERE id=?",
            (status, note, note, time.time(), follow_up, job_id))
        self.add_event(job_id, "status", f"{status}" + (f": {note}" if note else ""))
        self.conn.commit()

    def due_followups(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, data, follow_up FROM jobs WHERE status='applied' AND follow_up IS NOT NULL"
            " AND follow_up <= ?", (time.time(),)).fetchall()
        return [{"id": r["id"], "follow_up": r["follow_up"],
                 "title": json.loads(r["data"]).get("title", ""),
                 "company": json.loads(r["data"]).get("company", "")} for r in rows]

    def list_jobs(self, status: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM jobs" + (" WHERE status=?" if status else "") + " ORDER BY updated DESC"
        rows = self.conn.execute(q, (status,) if status else ()).fetchall()
        out = []
        for r in rows:
            job = JobPosting.from_dict(json.loads(r["data"]))
            out.append({"id": r["id"], "title": job.title, "company": job.company,
                        "location": job.location, "url": job.url, "source": job.source,
                        "status": r["status"], "score": r["score"],
                        "policy_verdict": r["policy_verdict"], "notes": r["notes"],
                        "updated": r["updated"],
                        "verification": self.verification_summary(r["id"])})
        return out

    # evidence-backed company legitimacy and application routes
    def set_verification(self, job_id: str, verification) -> None:
        errors = verification.validate()
        if errors:
            raise ValueError("; ".join(errors))
        self.conn.execute(
            "INSERT INTO company_verifications (job_id,data,updated) VALUES (?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
            (job_id, json.dumps(verification.to_dict()), time.time()))
        self.add_event(job_id, "company_verification", verification.status)
        self.conn.commit()

    def get_verification(self, job_id: str):
        from .verification import CompanyVerification
        row = self.conn.execute(
            "SELECT data FROM company_verifications WHERE job_id=?", (job_id,)).fetchone()
        return CompanyVerification.from_dict(json.loads(row["data"])) if row else None

    def verification_summary(self, job_id: str) -> dict[str, Any]:
        result = self.get_verification(job_id)
        if not result:
            return {"status": "unknown", "route": ""}
        route = result.best_route()
        return {"status": result.status, "route": route.value if route else ""}

    # events
    def add_event(self, job_id: str | None, kind: str, detail: str = "") -> None:
        self.conn.execute("INSERT INTO events (job_id,ts,kind,detail) VALUES (?,?,?,?)",
                          (job_id, time.time(), kind, detail))
        self.conn.commit()

    def events(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()

    # pending questions (batched user decisions)
    def add_pending(self, question: str, job_id: str | None = None) -> None:
        self.conn.execute("INSERT INTO pending (job_id,question,asked) VALUES (?,?,?)",
                          (job_id, question, time.time()))
        self.conn.commit()

    def pending(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM pending WHERE answer IS NULL ORDER BY asked").fetchall()

    def answer_pending(self, pending_id: int, answer: str) -> None:
        self.conn.execute("UPDATE pending SET answer=?, answered=? WHERE id=?",
                          (answer, time.time(), pending_id))
        self.conn.commit()

    # learned preferences
    def set_pref(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO prefs (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, value))
        self.conn.commit()

    def get_pref(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # agent runtime: worker task queue
    def enqueue_task(self, kind: str, payload: dict | None = None) -> int:
        now = time.time()
        cur = self.conn.execute(
            "INSERT INTO tasks (kind,payload,status,created,updated) VALUES (?,?,?,?,?)",
            (kind, json.dumps(payload or {}), "queued", now, now))
        self.conn.commit()
        return int(cur.lastrowid)

    def claim_task(self) -> sqlite3.Row | None:
        self.conn.execute("BEGIN IMMEDIATE")
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row:
            self.conn.execute(
                "UPDATE tasks SET status='running', attempts=attempts+1, updated=? WHERE id=?",
                (time.time(), row["id"]))
        self.conn.commit()
        return row

    def complete_task(self, task_id: int, result: str = "") -> None:
        self.conn.execute("UPDATE tasks SET status='done', result=?, updated=? WHERE id=?",
                          (result, time.time(), task_id))
        self.conn.commit()

    def fail_task(self, task_id: int, error: str, max_attempts: int = 3) -> str:
        row = self.conn.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
        status = "failed" if (row and row["attempts"] >= max_attempts) else "queued"
        self.conn.execute("UPDATE tasks SET status=?, result=?, updated=? WHERE id=?",
                          (status, error, time.time(), task_id))
        self.conn.commit()
        return status

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        q = "SELECT * FROM tasks" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT ?"
        return self.conn.execute(q, (status, limit) if status else (limit,)).fetchall()

    # conversation log shared by the CLI and web UI clients
    def log_message(self, role: str, text: str) -> None:
        self.conn.execute("INSERT INTO messages (ts,role,text) VALUES (?,?,?)",
                          (time.time(), role, text))
        self.conn.commit()

    def conversation(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}

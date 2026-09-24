"""Local SQLite tracker: jobs, events, pending questions, learned preferences."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
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
  qualification_decision TEXT,
  qualification_data TEXT DEFAULT '{}',
  liveness TEXT NOT NULL DEFAULT 'unknown',
  liveness_detail TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS email_hunts (
  job_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  outcome TEXT NOT NULL DEFAULT 'pending',
  outcome_detail TEXT DEFAULT '',
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS company_verifications (
  job_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agencies (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'discovered',
  country TEXT DEFAULT '',
  first_seen REAL NOT NULL,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_links (
  job_id TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  first_seen REAL NOT NULL,
  UNIQUE(job_id, source, url)
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
        except sqlite3.OperationalError:
            pass  # column already exists
        for column, ddl in (("qualification_decision", "TEXT"),
                            ("qualification_data", "TEXT DEFAULT '{}'"),
                            ("liveness", "TEXT NOT NULL DEFAULT 'unknown'"),
                            ("liveness_detail", "TEXT DEFAULT ''")):
            try:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

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
                        "decision": r["qualification_decision"],
                        "qualification": json.loads(r["qualification_data"] or "{}"),
                        "liveness": r["liveness"],
                        "liveness_detail": r["liveness_detail"],
                        "verification": self.verification_summary(r["id"]),
                        "salary_text": job.salary_text,
                        "contact_emails": job.contact_emails,
                        "email": self.email_summary(r["id"])})
        return out


    def set_liveness(self, job_id: str, status: str, detail: str = "") -> None:
        if status not in {"alive", "expired", "unknown"}:
            raise ValueError(f"unknown liveness {status}")
        self.conn.execute("UPDATE jobs SET liveness=?, liveness_detail=?, updated=? WHERE id=?",
                          (status, detail, time.time(), job_id))
        self.add_event(job_id, "liveness", f"{status}: {detail}")
        self.conn.commit()

    def set_qualification(self, job_id: str, result, signals) -> None:
        payload = {"result": result.to_dict(), "signals": asdict(signals)}
        status = {"strong": "shortlisted", "policy_review": "needs_input",
                  "insufficient_evidence": "needs_input", "plausible": "needs_input",
                  "stale": "skipped", "reject": "rejected"}[result.decision]
        self.conn.execute(
            "UPDATE jobs SET qualification_decision=?, qualification_data=?, status=?, notes=?, updated=? WHERE id=?",
            (result.decision, json.dumps(payload), status, "; ".join(result.reasons), time.time(), job_id))
        self.add_event(job_id, "qualification", f"{result.decision}: " + "; ".join(result.reasons))
        self.conn.commit()

    def qualification(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT qualification_decision,qualification_data FROM jobs WHERE id=?",
                                (job_id,)).fetchone()
        return {"decision": None, "result": {}, "signals": {}} if not row else {
            "decision": row["qualification_decision"],
            **json.loads(row["qualification_data"] or "{}")
        }

    def require_strong(self, job_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        status = row["status"] if row else None
        decision = self.qualification(job_id).get("decision")
        # Defense in depth: manual status changes or legacy/corrupt rows must not
        # revive a terminal job even if an old decision still says strong.
        if status in {"skipped", "rejected", "stale"}:
            return f"job is not actionable: tracker status is {status}"
        if decision != "strong":
            return f"job is not actionable: qualification decision is {decision or 'not computed'}; run triage after verification and liveness checks"
        return None

    # alternate source links for the same role across boards
    def add_link(self, job_id: str, source: str, url: str) -> bool:
        if not url:
            return False
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO job_links (job_id,source,url,first_seen) VALUES (?,?,?,?)",
            (job_id, source or "unknown", url, time.time()))
        self.conn.commit()
        return cur.rowcount > 0

    def links(self, job_id: str) -> list[dict[str, str]]:
        rows = self.conn.execute(
            "SELECT source, url FROM job_links WHERE job_id=? ORDER BY first_seen",
            (job_id,)).fetchall()
        return [{"source": r["source"], "url": r["url"]} for r in rows]

    def find_duplicate_job(self, job: JobPosting) -> JobPosting | None:
        """Match a fetched job against already-tracked roles (canonical URL,
        then normalized company/title/location signature)."""
        from .dedupe import find_duplicate
        rows = self.conn.execute("SELECT data FROM jobs").fetchall()
        existing = [JobPosting.from_dict(json.loads(r["data"])) for r in rows]
        return find_duplicate(job, existing)

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

    # email hunts: the second delivery route next to the portal application
    EMAIL_OUTCOMES = ("pending", "sent", "failed")

    def set_email_hunt(self, job_id: str, hunt) -> None:
        """Store an EmailHunt. Keeps an existing 'sent' outcome; a new hunt after
        a failed send resets the row to pending so it is retried."""
        row = self.conn.execute("SELECT outcome FROM email_hunts WHERE job_id=?", (job_id,)).fetchone()
        outcome = row["outcome"] if row and row["outcome"] == "sent" else "pending"
        self.conn.execute(
            "INSERT INTO email_hunts (job_id,data,outcome,updated) VALUES (?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET data=excluded.data, outcome=excluded.outcome, "
            "updated=excluded.updated",
            (job_id, json.dumps(hunt.to_dict()), outcome, time.time()))
        self.add_event(job_id, "email_hunt", hunt.summary())
        self.conn.commit()

    def get_email_hunt(self, job_id: str):
        from .emailfinder import EmailHunt
        row = self.conn.execute("SELECT data FROM email_hunts WHERE job_id=?", (job_id,)).fetchone()
        return EmailHunt.from_dict(json.loads(row["data"])) if row else None

    def set_email_outcome(self, job_id: str, outcome: str, detail: str = "") -> None:
        """Record what happened to the follow-up email. 'sent' needs proof in
        detail (e.g. the sent-message id or link)."""
        if outcome not in self.EMAIL_OUTCOMES:
            raise ValueError(f"outcome must be one of {self.EMAIL_OUTCOMES}")
        if outcome == "sent" and not detail.strip():
            raise ValueError("a sent email needs proof: the sent-message id or link")
        hunt = self.get_email_hunt(job_id)
        if outcome == "sent" and (hunt is None or not hunt.verified()):
            raise ValueError("no verified address on record for this job; run the email hunt first")
        self.conn.execute("UPDATE email_hunts SET outcome=?, outcome_detail=?, updated=? WHERE job_id=?",
                          (outcome, detail, time.time(), job_id))
        self.add_event(job_id, f"email_{outcome}", detail)
        self.conn.commit()

    def email_summary(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT data, outcome, outcome_detail FROM email_hunts WHERE job_id=?",
                                (job_id,)).fetchone()
        if not row:
            return {"hunt": "not_run", "address": "", "outcome": "pending", "detail": ""}
        from .emailfinder import EmailHunt
        hunt = EmailHunt.from_dict(json.loads(row["data"]))
        best = hunt.best()
        return {"hunt": hunt.status, "address": best.address if best else "",
                "source": best.source_url if best else "",
                "outcome": row["outcome"], "detail": row["outcome_detail"] or "",
                "missing_methods": hunt.missing_methods()}

    def email_stage_counts(self) -> dict[str, int]:
        """Applied roles split by the email route: sent, pending, failed,
        no verified address (every method ran), or hunt not finished."""
        counts = {"applied_email_sent": 0, "applied_email_pending": 0,
                  "applied_email_failed": 0, "applied_no_verified_address": 0,
                  "applied_hunt_incomplete": 0}
        for r in self.conn.execute("SELECT id FROM jobs WHERE status='applied'").fetchall():
            e = self.email_summary(r["id"])
            if e["outcome"] == "sent":
                counts["applied_email_sent"] += 1
            elif e["outcome"] == "failed":
                counts["applied_email_failed"] += 1
            elif e["hunt"] == "found":
                counts["applied_email_pending"] += 1
            elif e["hunt"] == "no_verified_address":
                counts["applied_no_verified_address"] += 1
            else:
                counts["applied_hunt_incomplete"] += 1
        return counts

    def jobs_needing_email_hunt(self, statuses=("applied", "ready", "shortlisted", "tailored")) -> list[str]:
        """Jobs whose hunt never ran, is incomplete, or whose send failed."""
        marks = ",".join("?" for _ in statuses)
        out = []
        for r in self.conn.execute(f"SELECT id FROM jobs WHERE status IN ({marks}) ORDER BY updated DESC",
                                   tuple(statuses)).fetchall():
            e = self.email_summary(r["id"])
            if e["outcome"] == "failed" or e["hunt"] in ("not_run", "incomplete"):
                out.append(r["id"])
        return out

    # recruitment agencies (see agencies.py)
    def upsert_agency(self, agency, previous_id: str | None = None) -> str:
        """Store an Agency. An existing record keeps its facts (new ones are
        added) and a 'contacted' agency keeps its status and proof. When
        validation found the website of a name-only record its id changes;
        pass previous_id and the old row is folded into the new one."""
        from .agencies import Agency
        if previous_id and previous_id != agency.id:
            prev = self.get_agency(previous_id)
            if prev is not None:
                agency.merge(prev)
                if prev.status == "contacted":
                    agency.status, agency.contact_proof = prev.status, prev.contact_proof
                self.conn.execute("DELETE FROM agencies WHERE id=?", (previous_id,))
        row = self.conn.execute("SELECT data FROM agencies WHERE id=?", (agency.id,)).fetchone()
        now = time.time()
        if row:
            old = Agency.from_dict(json.loads(row["data"]))
            if agency.checks:
                old.checks = agency.checks
                old.email_hunt = agency.email_hunt or old.email_hunt
                old.checked_at = agency.checked_at
                if old.status != "contacted":
                    old.status = agency.status
                    old.contact_email = agency.contact_email
                    old.contact_source = agency.contact_source
            old.merge(agency)
            agency = old
            self.conn.execute("UPDATE agencies SET data=?, status=?, country=?, updated=? WHERE id=?",
                              (json.dumps(agency.to_dict()), agency.status, agency.country, now, agency.id))
        else:
            self.conn.execute("INSERT INTO agencies (id,data,status,country,first_seen,updated) VALUES (?,?,?,?,?,?)",
                              (agency.id, json.dumps(agency.to_dict()), agency.status, agency.country, now, now))
            self.add_event(None, "agency_discovered", f"{agency.id} {agency.name}")
        self.conn.commit()
        return agency.id

    def get_agency(self, agency_id: str):
        from .agencies import Agency
        row = self.conn.execute("SELECT data FROM agencies WHERE id=?", (agency_id,)).fetchone()
        return Agency.from_dict(json.loads(row["data"])) if row else None

    def list_agencies(self, status: str | None = None, country: str | None = None) -> list:
        from .agencies import Agency
        q, params = "SELECT data FROM agencies WHERE 1=1", []
        if status:
            q += " AND status=?"; params.append(status)
        if country:
            q += " AND lower(country)=lower(?)"; params.append(country)
        rows = self.conn.execute(q + " ORDER BY updated DESC", tuple(params)).fetchall()
        return [Agency.from_dict(json.loads(r["data"])) for r in rows]

    def resolve_agency_id(self, query: str) -> str | None:
        query = (query or "").strip()
        if not query:
            return None
        if self.conn.execute("SELECT 1 FROM agencies WHERE id=?", (query,)).fetchone():
            return query
        hits = [a.id for a in self.list_agencies()
                if query.lower() in a.name.lower() or (a.domain and query.lower() == a.domain)]
        return hits[0] if len(hits) == 1 else None

    def set_agency_contacted(self, agency_id: str, proof: str) -> None:
        """Mark an agency contacted. Needs a verified contact address on
        record and proof (sent-message id or link)."""
        agency = self.get_agency(agency_id)
        if agency is None:
            raise ValueError(f"no agency '{agency_id}'")
        if not proof.strip():
            raise ValueError("contacted needs proof: the sent-message id or link")
        if agency.status not in ("validated", "contacted") or not agency.contact_email:
            raise ValueError("agency has no verified contact address; validate it first")
        agency.status, agency.contact_proof = "contacted", proof.strip()
        self.conn.execute("UPDATE agencies SET data=?, status=?, updated=? WHERE id=?",
                          (json.dumps(agency.to_dict()), agency.status, time.time(), agency_id))
        self.add_event(None, "agency_contacted", f"{agency_id} {agency.contact_email} proof: {proof.strip()}")
        self.conn.commit()

    def agency_counts(self) -> dict[str, int]:
        from .agencies import STATUSES as AGENCY_STATUSES
        counts = {s: 0 for s in AGENCY_STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM agencies GROUP BY status").fetchall():
            counts[r["status"]] = r["c"]
        return counts

    def all_jobs(self) -> list[JobPosting]:
        return [JobPosting.from_dict(json.loads(r["data"]))
                for r in self.conn.execute("SELECT data FROM jobs").fetchall()]

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

    def add_pending_once(self, question: str, job_id: str | None = None) -> bool:
        """Record a distinct review question once, including after it is answered."""
        row = self.conn.execute(
            "SELECT 1 FROM pending WHERE question=? AND "
            "((job_id IS NULL AND ? IS NULL) OR job_id=?) LIMIT 1",
            (question, job_id, job_id)).fetchone()
        if row:
            return False
        self.add_pending(question, job_id=job_id)
        return True

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

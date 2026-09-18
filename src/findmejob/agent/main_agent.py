"""The persistent main job agent.

One agent owns the conversation, your preferences, planning, tracker state,
blocker batching and follow-through. The CLI and the web UI are two clients
of this same agent and the same SQLite state, so a conversation started in
the terminal continues in the browser with full history.

The main agent never does source/apply work itself: it enqueues AgentTasks
and runs focused workers (see workers.py). A worker that needs a human
decision pauses only its own job; the question lands in the pending list and
everything else keeps moving.

Conversation runs on a deterministic brain by default (no LLM needed). Set an
LLM provider in config.json to let the agent also handle freeform chat; the
pipeline and safety rules stay the same either way.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import Config
from ..tracker import Tracker
from .workers import run_worker

HELP = (
    "I can find roles, score them against your CV, tailor your CV, draft a "
    "short application email, and run a browser application that stops before "
    "submit. Try: 'find jobs', 'status', 'what's pending', 'tailor <role>', "
    "'apply <role>', 'verify <role>', 'skip <role>' - or tell me a preference "
    "like 'my salary floor is 120000'."
)


class MainAgent:
    def __init__(self, cfg: Config, tracker: Tracker):
        self.cfg = cfg
        self.tracker = tracker

    # --- conversation entry point (shared by CLI and web UI) ---
    def handle(self, message: str) -> str:
        msg = message.strip()
        self.tracker.log_message("user", msg)
        reply = self._route(msg)
        self.tracker.log_message("agent", reply)
        return reply

    # --- worker pump ---
    def tick(self) -> list[str]:
        """Run queued worker tasks. Returns human-readable summaries."""
        summaries: list[str] = []
        while True:
            row = self.tracker.claim_task()
            if not row:
                break
            payload = json.loads(row["payload"] or "{}")
            try:
                res = run_worker(row["kind"], payload, self.cfg, self.tracker)
            except Exception as exc:
                status = self.tracker.fail_task(row["id"], str(exc))
                summaries.append(f"{row['kind']} failed ({status}): {exc}")
                continue
            for question in res.needs_user:
                self._add_pending_once(question, payload.get("job"))
            self.tracker.complete_task(row["id"], res.summary)
            self.tracker.add_event(None, "worker", f"{row['kind']}: {res.summary}")
            summaries.append(res.summary)
        return summaries

    # --- routing ---
    def _route(self, msg: str) -> str:
        low = msg.lower()
        if not msg:
            return HELP
        if low in ("help", "hi", "hello", "hey"):
            return "Hey. " + HELP
        if re.search(r"\bwhat'?s pending\b|\bpending\b|\banything (waiting|pending)\b", low):
            return self._pending_reply()
        if re.search(r"\bfind (me )?(jobs|roles)|\bsearch\b|\blook for jobs\b", low):
            self.tracker.enqueue_task("source")
            summaries = self.tick()
            return summaries[-1] if summaries else "Search ran; nothing new."
        if low in ("status", "stats", "overview"):
            return self._status_reply()
        m = re.match(r"(?:tailor|cv for|prepare)\s+(.+)", msg, re.IGNORECASE)
        if m:
            return self._task_reply("tailor", {"job": m.group(1)})
        m = re.match(r"(?:verify|check)\s+(.+)", msg, re.IGNORECASE)
        if m:
            return self._task_reply("verify", {"job": m.group(1)})
        m = re.match(r"(?:skip|reject|pass on)\s+(.+)", msg, re.IGNORECASE)
        if m:
            return self._mark(m.group(1), "skipped")
        m = re.match(r"(?:mark applied|i applied to|applied)\s+(.+)", msg, re.IGNORECASE)
        if m:
            return self._mark(m.group(1), "applied")
        m = re.match(r"(?:apply|start apply)(?: to)?\s+(.+)", msg, re.IGNORECASE)
        if m:
            query = m.group(1).strip()
            job_id = self.tracker.resolve_job_id(query)
            if not job_id:
                return f"No tracked job matches '{query}'."
            submit = "submit" in low and not self.cfg.autonomy["require_confirmation"]
            return self._task_reply("apply", {"job": job_id, "submit": submit})

        m = re.search(r"use (?:runtime|model|provider)[:\s]+([\w\- ]{2,30})$", low)
        if m:
            return self._set_runtime(m.group(1).strip())
        if low in ("runtimes", "which runtime", "what runtime"):
            return self._runtime_reply()

        pref = self._learn_preference(low)
        if pref:
            return pref

        pending = self.tracker.pending()
        if pending:
            row = pending[0]
            self.tracker.answer_pending(row["id"], msg)
            if row["job_id"]:
                self.tracker.set_status(row["job_id"], "shortlisted", "answered: " + msg[:120])
            left = len(self.tracker.pending())
            more = f" {left} more question(s) waiting." if left else " Nothing else pending."
            return f"Got it, recorded as the answer to: \"{row['question']}\".{more}"

        return HELP

    # --- helpers ---
    def _task_reply(self, kind: str, payload: dict) -> str:
        self.tracker.enqueue_task(kind, payload)
        summaries = self.tick()
        reply = "\n".join(summaries) if summaries else f"{kind} ran with no result."
        left = len(self.tracker.pending())
        if left:
            reply += f"\n{left} question(s) now waiting on you - say 'what's pending' to see them."
        return reply

    def _add_pending_once(self, question: str, job_id: str | None) -> None:
        for r in self.tracker.pending():
            if r["question"] == question:
                return
        self.tracker.add_pending(question, job_id=job_id)

    def _pending_reply(self) -> str:
        rows = self.tracker.pending()
        if not rows:
            return "Nothing is waiting on you. Say 'find jobs' and I will keep looking."
        lines = [f"{len(rows)} thing(s) need your call:"]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. {r['question']}")
        lines.append("Answer them here one by one, or say 'skip <job>' to drop one.")
        return "\n".join(lines)

    def _status_reply(self) -> str:
        counts = self.tracker.counts()
        due = self.tracker.due_followups()
        if not counts and not due:
            return "Tracker is empty. Say 'find jobs' to start."
        parts = [f"{k}: {v}" for k, v in sorted(counts.items())]
        pend = len(self.tracker.pending())
        reply = "Jobs - " + ", ".join(parts) if parts else "No tracked jobs."
        if pend:
            reply += f". {pend} pending question(s)."
        if due:
            reply += "\nFollow-ups due: " + "; ".join(
                f"{d['title']} @ {d['company']}" for d in due)
        return reply

    def _mark(self, query: str, status: str) -> str:
        job_id = self.tracker.resolve_job_id(query)
        if not job_id:
            return f"No tracked job matches '{query}'."
        self.tracker.set_status(job_id, status)
        return f"Marked {job_id} as {status}."

    def _set_runtime(self, name: str) -> str:
        from ..runtimes import detect_runtimes
        aliases = {"claude": "anthropic", "claude code": "claude-code",
                   "openai": "openai", "gpt": "openai", "local": "ollama"}
        name = aliases.get(name, name)
        known = {r.name: r for r in detect_runtimes()}
        rt = known.get(name)
        if not rt:
            return "Unknown runtime. Options: " + ", ".join(sorted(known))
        if not rt.available:
            return f"{name} is not available here. {rt.setup_hint}"
        if rt.kind in ("api", "local"):
            self._update_config("llm", "provider", name)
        self.tracker.set_pref("runtime", name)
        return f"Runtime set to {name}. {rt.setup_hint}"

    def _runtime_reply(self) -> str:
        from ..runtimes import detect_runtimes, select_runtime
        current = select_runtime(self.cfg.llm.get("provider", ""))
        lines = [f"Current runtime: {current.name}.", "Available runtimes:"]
        for r in detect_runtimes():
            mark = "yes" if r.available else "no"
            lines.append(f"- {r.name} ({r.kind}), available: {mark}")
        lines.append("Say 'use runtime <name>' to switch.")
        return "\n".join(lines)

    def _learn_preference(self, low: str) -> str | None:
        m = re.search(r"salary floor (?:is |of )?\$?([\d,]+)", low)
        if m:
            floor = int(m.group(1).replace(",", ""))
            self._update_config("policy", "salary_floor", floor)
            self.tracker.set_pref("salary_floor", str(floor))
            return f"Noted: salary floor {floor}. Applied from the next search on."
        if re.search(r"(?:i |i'd |i would )?prefer remote|remote only", low):
            self._update_config_list("policy", "locations_include", "Remote")
            self.tracker.set_pref("remote_only", "true")
            return "Noted: remote roles preferred."
        m = re.search(r"exclude ([\w \-]{2,40})$", low)
        if m:
            word = m.group(1).strip()
            self._update_config_list("policy", "sector_exclusions", word)
            return f"Noted: I will exclude roles mentioning '{word}'."
        m = re.search(r"(?:also )?(?:look for|target|include) ([\w \-]{3,50}) roles?$", low)
        if m:
            kw = m.group(1).strip()
            self._update_config_list("search", "role_keywords", kw)
            return f"Noted: added '{kw}' to target roles."
        return None

    def _update_config(self, section: str, key: str, value: Any) -> None:
        cfg_path = self.cfg.root / "config.json"
        data = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        data.setdefault(section, {})[key] = value
        cfg_path.write_text(json.dumps(data, indent=2) + "\n")
        self.cfg.raw = data

    def _update_config_list(self, section: str, key: str, value: str) -> None:
        cfg_path = self.cfg.root / "config.json"
        data = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        lst = data.setdefault(section, {}).setdefault(key, [])
        if value not in lst:
            lst.append(value)
        cfg_path.write_text(json.dumps(data, indent=2) + "\n")
        self.cfg.raw = data

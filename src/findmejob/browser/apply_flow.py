"""Browser-assisted application flow.

Dry-run by default: navigate, check guards, fill known fields, screenshot,
stop before submit. Final submit happens only with submit=True AND the
config autonomy gate allowing it. Every pause is recorded in the tracker so
the chat UI can batch it with the other pending decisions.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..config import Config
from ..models import JobPosting, Profile
from ..tracker import Tracker
from .guards import PausedForHuman, StopReason, check_page
from .session import open_session

KNOWN_FIELD_MAP = {
    "name": "full_name", "full name": "full_name", "email": "email",
    "phone": "phone", "linkedin": "linkedin", "website": "website",
    "portfolio": "portfolio", "github": "github",
}


def _known_answers(profile: Profile) -> dict[str, str]:
    answers = {"full name": profile.full_name, "name": profile.full_name,
               "email": profile.email, "phone": profile.phone}
    for k, v in profile.links.items():
        answers[k] = v
    return {k: v for k, v in answers.items() if v}


def apply_to_job(job: JobPosting, profile: Profile, cfg: Config, tracker: Tracker,
                 submit: bool = False, headless: bool = False,
                 screenshot_dir: Path | None = None) -> dict:
    result = {"job_id": job.id, "status": "started", "stop": None, "screenshot": None}
    auto = cfg.autonomy
    screenshot_dir = screenshot_dir or (cfg.output_dir / "screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    pw, ctx = open_session(cfg.resolve(cfg.paths["browser_profile"]), headless=headless)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        text = page.inner_text("body")[:20000]
        try:
            check_page(text, never_pay=auto["never_pay"],
                       never_create_accounts=auto["never_create_accounts"])
        except PausedForHuman as pause:
            result["status"] = "paused"
            result["stop"] = pause.reason.kind
            shot = screenshot_dir / f"{job.id}_paused.png"
            page.screenshot(path=str(shot), full_page=False)
            result["screenshot"] = str(shot)
            tracker.set_status(job.id, "needs_input", f"paused: {pause.reason.kind}")
            tracker.add_pending(pause.reason.detail, job_id=job.id)
            return result

        answers = _known_answers(profile)
        filled = 0
        for el in page.query_selector_all("input[type=text], input[type=email], input[type=tel], input:not([type])"):
            try:
                label = (el.get_attribute("aria-label") or el.get_attribute("placeholder")
                         or el.get_attribute("name") or "").strip()
            except Exception:
                continue
            key = label.lower()
            if key in answers and not el.input_value():
                el.fill(answers[key])
                filled += 1
        shot = screenshot_dir / f"{job.id}_filled.png"
        page.screenshot(path=str(shot), full_page=False)
        result["screenshot"] = str(shot)
        tracker.add_event(job.id, "apply_fill", f"filled {filled} known fields")

        if not submit:
            result["status"] = "dry_run_complete"
            tracker.set_status(job.id, "ready", "form pre-filled, awaiting your review and submit")
            return result
        if auto["require_confirmation"] and not auto["auto_apply"]:
            result["status"] = "paused"
            result["stop"] = "submit_gate"
            tracker.set_status(job.id, "needs_input", "waiting for your submit confirmation")
            tracker.add_pending("Confirm final submit of the application form", job_id=job.id)
            return result
        result["status"] = "submit_left_to_user"
        result["stop"] = "submit_gate"
        return result
    finally:
        ctx.close()
        pw.stop()

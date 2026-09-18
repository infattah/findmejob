"""Shared pipeline steps used by both the CLI and the chat engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .emailer import save_draft
from .models import JobPosting, Profile
from .policy import check_job
from .profile import parse_master_cv, extract_text
from .scoring import score_fit
from .sources import fetch_all
from .tailor import check_fidelity, render_cv_markdown
from .tracker import Tracker


def load_profile(cfg: Config) -> Profile:
    cv_rel = cfg.profile.get("master_cv", "")
    cv_path = cfg.resolve(cv_rel) if cv_rel else None
    if not cv_path or not cv_path.exists():
        raise FileNotFoundError(
            "No master CV found. Run: findmejob ingest --cv path/to/your_cv.md")
    profile = parse_master_cv(extract_text(cv_path))
    for k in ("full_name", "email", "phone"):
        if cfg.profile.get(k) and not getattr(profile, k):
            setattr(profile, k, cfg.profile[k])
    if cfg.profile.get("links"):
        profile.links.update(cfg.profile["links"])
    return profile


def run_search(cfg: Config, tracker: Tracker) -> dict[str, Any]:
    specs = cfg.search.get("sources", [])
    jobs, errors = fetch_all(specs)
    new_count = 0
    for job in jobs:
        verdict = check_job(job, cfg.policy)
        status = "new"
        if verdict.verdict == "block":
            status = "skipped"
        if tracker.upsert_job(job, verdict=verdict.verdict, status=status):
            new_count += 1
            if verdict.verdict == "block":
                tracker.add_event(job.id, "policy_block", "; ".join(verdict.reasons))
    tracker.add_event(None, "search", f"{len(jobs)} fetched, {new_count} new, {len(errors)} source errors")
    return {"fetched": len(jobs), "new": new_count, "errors": errors}


def run_triage(cfg: Config, tracker: Tracker) -> dict[str, Any]:
    profile = load_profile(cfg)
    role_keywords = cfg.search.get("role_keywords", [])
    min_score = int(cfg.policy.get("min_fit_score", 0))
    shortlisted = blocked = needs = 0
    for row in tracker.list_jobs(status="new"):
        job = tracker.get_job(row["id"])
        if not job:
            continue
        fit = score_fit(profile, job, role_keywords)
        verdict = row["policy_verdict"] or "pass"
        if verdict == "review":
            tracker.set_status(job.id, "needs_input", "; ".join(check_job(job, cfg.policy).reasons))
            tracker.add_pending(
                f"Review policy question for {job.title} @ {job.company}: "
                + "; ".join(check_job(job, cfg.policy).reasons), job_id=job.id)
            needs += 1
        elif fit.score >= min_score:
            tracker.conn.execute("UPDATE jobs SET score=?, status='shortlisted', updated=? WHERE id=?",
                                 (fit.score, __import__("time").time(), job.id))
            tracker.add_event(job.id, "shortlist", f"score {fit.score}: " + "; ".join(fit.reasons[:3]))
            tracker.conn.commit()
            shortlisted += 1
        else:
            tracker.conn.execute("UPDATE jobs SET score=? WHERE id=?", (fit.score, job.id))
            tracker.conn.commit()
            blocked += 1
    return {"shortlisted": shortlisted, "needs_review": needs, "below_floor": blocked}


def run_tailor(cfg: Config, tracker: Tracker, job_query: str) -> dict[str, Any]:
    profile = load_profile(cfg)
    job_id = tracker.resolve_job_id(job_query)
    if not job_id:
        return {"error": f"no job matching '{job_query}'"}
    job = tracker.get_job(job_id)
    assert job
    cv_md = render_cv_markdown(profile, job)
    warnings = check_fidelity(profile.all_facts_text(), cv_md)
    cv_dir = cfg.output_dir / "cvs"
    cv_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in f"{profile.full_name}_{job.company}_{job.title}")[:80]
    cv_path = cv_dir / f"{safe}_{job.id}.md"
    cv_path.write_text(cv_md, encoding="utf-8")
    email_path = save_draft(cfg.output_dir / "emails", profile, job, cfg, attachment=cv_path)
    tracker.set_status(job.id, "tailored", f"CV: {cv_path.name}")
    tracker.add_event(job.id, "tailor", f"fidelity warnings: {len(warnings)}")
    return {"job_id": job.id, "cv": str(cv_path), "email": str(email_path),
            "fidelity_warnings": warnings}

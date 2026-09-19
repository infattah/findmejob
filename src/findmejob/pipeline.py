"""Shared pipeline steps used by both the CLI and the chat engine."""
from __future__ import annotations

import re

from pathlib import Path
from typing import Any

from .config import Config
from .dedupe import dedupe_batch
from .emailer import save_draft
from .httpcache import HttpCache
from .models import JobPosting, Profile
from .policy import check_job
from .profile import parse_master_cv, extract_text
from .render.pdf import render_cv_pdf
from .scoring import score_fit
from .sources import fetch_all
from .sources.base import configure_cache
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


def _build_cache(cfg: Config) -> HttpCache | None:
    ttl = cfg.search.get("cache_ttl_seconds")
    if ttl is None:
        ttl = 3600  # caching is on by default; set 0 to disable
    ttl = int(ttl)
    if ttl <= 0:
        return None
    return HttpCache(cfg.resolve(cfg.paths.get("cache", "data/http-cache")), ttl)


def run_search(cfg: Config, tracker: Tracker) -> dict[str, Any]:
    # Source paths in config.json are relative to the project root, not the
    # shell's current directory. This keeps --dir and the web UI consistent.
    specs = []
    for raw_spec in cfg.search.get("sources", []):
        spec = dict(raw_spec)
        if spec.get("type") == "jsonfile" and spec.get("path"):
            spec["path"] = str(cfg.resolve(spec["path"]))
        specs.append(spec)
    cache = _build_cache(cfg)
    configure_cache(cache)
    try:
        jobs, errors = fetch_all(specs)
    finally:
        configure_cache(None)

    # cross-source dedupe: within this batch, then against the tracker
    unique, batch_dupes = dedupe_batch(jobs)
    new_count = dup_count = 0
    def remember_routes(job_id, job):
        routes=[(job.source, job.url)]
        if getattr(job,"apply_url","") and job.apply_url != job.url:
            routes.append((job.source+":apply",job.apply_url))
        return sum(bool(url) and tracker.add_link(job_id,source,url) for source,url in routes)
    for job in unique:
        existing = tracker.find_duplicate_job(job)
        if existing is not None:
            added=remember_routes(existing.id,job)
            if added:
                tracker.add_event(existing.id, "duplicate",
                                  f"also seen at {job.source}: {job.url}")
            dup_count += 1
            continue
        verdict = check_job(job, cfg.policy)
        status = "new"
        if verdict.verdict == "block":
            status = "skipped"
        if tracker.upsert_job(job, verdict=verdict.verdict, status=status):
            remember_routes(job.id,job)
            new_count += 1
            if verdict.verdict == "block":
                tracker.add_event(job.id, "policy_block", "; ".join(verdict.reasons))
    for kept, dupe in batch_dupes:
        added=remember_routes(kept.id,dupe)
        if added:
            tracker.add_event(kept.id, "duplicate",
                              f"also seen at {dupe.source}: {dupe.url}")
        dup_count += 1
    tracker.add_event(None, "search",
                      f"{len(jobs)} fetched, {new_count} new, {dup_count} duplicates merged, "
                      f"{len(errors)} source errors")
    return {"fetched": len(jobs), "new": new_count, "duplicates": dup_count,
            "errors": errors}


def _has_substantive_job_evidence(job: JobPosting) -> bool:
    """Use evidence categories rather than length as a quality proxy."""
    text = job.description or ""
    if len(re.findall(r"[A-Za-z][A-Za-z0-9+#.-]*", text)) < 8:
        return False
    signals = 0
    if re.search(r"(?i)\b(?:lead|manage|own|build|create|develop|execute|optimi[sz]e|analy[sz]e|report|drive|launch|plan|deliver|responsible for|responsibilities include)\b", text):
        signals += 1
    if re.search(r"(?i)\b(?:requires?|qualifications?|must have|minimum|at least|\d+\s*\+?\s*years?)\b", text):
        signals += 1
    if re.search(r"(?i)\b(?:google ads|meta ads|paid social|paid media|analytics|cro|seo|sem|crm|hubspot|salesforce|programmatic|email marketing|a/b test|conversion rate)\b", text):
        signals += 1
    if re.search(r"(?i)\b(?:reports? to|reporting to|uae|mena|ecommerce|e-commerce|b2b|b2c|hybrid|remote|in-office)\b", text):
        signals += 1
    return signals >= 2


def run_triage(cfg: Config, tracker: Tracker, job_id: str | None = None) -> dict[str, Any]:
    from .evidence import evaluate_requirements
    from .qualification import qualify
    from .signal_adapter import build_signals
    profile = load_profile(cfg)
    counts = {"strong": 0, "plausible": 0, "insufficient_evidence": 0,
              "policy_review": 0, "stale": 0, "reject": 0}
    for row in tracker.list_jobs():
        if job_id is not None and row["id"] != job_id:
            continue
        if row["status"] == "applied":
            continue
        job = tracker.get_job(row["id"])
        if not job: continue
        fit = score_fit(profile, job, cfg.search.get("role_keywords", []))
        report = evaluate_requirements(profile, job)
        tracker.conn.execute("UPDATE jobs SET score=?, updated=? WHERE id=?", (fit.score, __import__("time").time(), job.id))
        tracker.conn.commit()
        _write_fit_report(cfg, tracker, profile, job, fit, report)
        signals = build_signals(profile=profile, job=job, policy=cfg.policy,
                                role_keywords=cfg.search.get("role_keywords", []), tracker=tracker)
        result = qualify(signals)
        tracker.set_qualification(job.id, result, signals)
        counts[result.decision] += 1
        if result.decision in {"plausible", "insufficient_evidence", "policy_review"}:
            tracker.add_pending_once(f"Review needed for {job.title} @ {job.company}: " + "; ".join(result.reasons), job_id=job.id)
    return {**counts, "shortlisted": counts["strong"],
            "needs_review": counts["plausible"] + counts["insufficient_evidence"] + counts["policy_review"],
            "below_floor": counts["reject"]}


def _write_fit_report(cfg: Config, tracker: Tracker, profile: Profile,
                      job: JobPosting, fit, report=None) -> None:
    from .evidence import evaluate_requirements, render_report_markdown
    report = report or evaluate_requirements(profile, job)
    fit_dir = cfg.output_dir / "fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    (fit_dir / f"{job.id}.md").write_text(
        render_report_markdown(report, fit.score, fit.reasons), encoding="utf-8")
    if report.items:
        tracker.add_event(job.id, "fit_report",
                          f"{report.strong} strong / {report.partial} partial / "
                          f"{report.missing} missing of {len(report.items)}")


def run_tailor(cfg: Config, tracker: Tracker, job_query: str) -> dict[str, Any]:
    profile = load_profile(cfg)
    job_id = tracker.resolve_job_id(job_query)
    if not job_id:
        return {"error": f"no job matching '{job_query}'"}
    job = tracker.get_job(job_id)
    if job is None:
        return {"error": "tracked job disappeared"}
    blocked = tracker.require_strong(job_id)
    if blocked:
        return {"error": blocked}
    cv_md = render_cv_markdown(profile, job)
    warnings = check_fidelity(profile.all_facts_text(), cv_md)
    cv_dir = cfg.output_dir / "cvs"
    cv_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in f"{profile.full_name}_{job.company}_{job.title}")[:80]
    cv_path = cv_dir / f"{safe}_{job.id}.md"
    cv_path.write_text(cv_md, encoding="utf-8")
    pdf_path = render_cv_pdf(profile, job, cv_dir / f"{safe}_{job.id}.pdf")
    email_path = save_draft(cfg.output_dir / "emails", profile, job, cfg, attachment=pdf_path)
    tracker.set_status(job.id, "tailored", f"CV: {cv_path.name}")
    tracker.add_event(job.id, "tailor", f"fidelity warnings: {len(warnings)}")
    return {"job_id": job.id, "cv": str(cv_path), "pdf": str(pdf_path),
            "email": str(email_path), "fidelity_warnings": warnings}

"""Shared pipeline steps used by both the CLI and the chat engine."""
from __future__ import annotations

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
    for job in unique:
        existing = tracker.find_duplicate_job(job)
        if existing is not None:
            if tracker.add_link(existing.id, job.source, job.url):
                tracker.add_event(existing.id, "duplicate",
                                  f"also seen at {job.source}: {job.url}")
                dup_count += 1
            continue
        verdict = check_job(job, cfg.policy)
        status = "new"
        if verdict.verdict == "block":
            status = "skipped"
        if tracker.upsert_job(job, verdict=verdict.verdict, status=status):
            new_count += 1
            if verdict.verdict == "block":
                tracker.add_event(job.id, "policy_block", "; ".join(verdict.reasons))
    for kept, dupe in batch_dupes:
        if tracker.add_link(kept.id, dupe.source, dupe.url):
            tracker.add_event(kept.id, "duplicate",
                              f"also seen at {dupe.source}: {dupe.url}")
            dup_count += 1
    tracker.add_event(None, "search",
                      f"{len(jobs)} fetched, {new_count} new, {dup_count} duplicates merged, "
                      f"{len(errors)} source errors")
    return {"fetched": len(jobs), "new": new_count, "duplicates": dup_count,
            "errors": errors}


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
        from .evidence import evaluate_requirements
        evidence = evaluate_requirements(profile, job)
        # Persist ranking independently of policy review. Salary uncertainty must
        # never erase fit metadata.
        tracker.conn.execute("UPDATE jobs SET score=?, updated=? WHERE id=?", (fit.score, __import__("time").time(), job.id))
        tracker.conn.commit()
        _write_fit_report(cfg, tracker, profile, job, fit, evidence)
        verdict = row["policy_verdict"] or "pass"
        hard_reasons = [f"hard requirement not proven: {i.requirement}" for i in evidence.items if i.hard and i.status != "strong"]
        if verdict == "review" or hard_reasons:
            policy_reasons = check_job(job, cfg.policy).reasons if verdict == "review" else []
            tracker.set_status(job.id, "needs_input", "; ".join(policy_reasons + hard_reasons))
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
    assert job
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

"""Application packs: one self-contained folder per role.

A pack gathers everything needed to apply and to follow up:
- job.json           the listing, its source links and company verification
- fit_report.md      evidence-based requirement check (strong/partial/missing)
- cv.md / cv.pdf     the tailored CV (Markdown source + designed PDF)
- email.txt          the application email draft
- checklist.md       application route, status and follow-up date

Files are canonical; the tracker only points at them.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import Config
from .emailer import save_draft
from .evidence import evaluate_requirements, render_report_markdown
from .pipeline import load_profile
from .render.pdf import render_cv_pdf
from .scoring import score_fit
from .tailor import check_fidelity, render_cv_markdown
from .tracker import Tracker


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)[:80].strip("_")


def build_pack(cfg: Config, tracker: Tracker, job_query: str) -> dict[str, Any]:
    job_id = tracker.resolve_job_id(job_query)
    if not job_id:
        return {"error": f"no job matching '{job_query}'"}
    job = tracker.get_job(job_id)
    if job is None:
        return {"error": "tracked job disappeared"}
    blocked = tracker.require_strong(job_id)
    if blocked:
        return {"error": blocked}
    profile = load_profile(cfg)

    pack_dir = cfg.output_dir / "packs" / f"{_safe_name(job.company)}_{job.id}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    from .priority import effective_role_keywords
    fit = score_fit(profile, job, effective_role_keywords(cfg.raw))
    report = evaluate_requirements(profile, job)
    report_path = pack_dir / "fit_report.md"
    report_path.write_text(render_report_markdown(report, fit.score, fit.reasons),
                           encoding="utf-8")

    cv_md = render_cv_markdown(profile, job)
    warnings = check_fidelity(profile.all_facts_text(), cv_md)
    cv_md_path = pack_dir / "cv.md"
    cv_md_path.write_text(cv_md, encoding="utf-8")
    cv_pdf_path = render_cv_pdf(profile, job, pack_dir / "cv.pdf")

    email_path = save_draft(pack_dir, profile, job, cfg, attachment=cv_pdf_path)
    email_path = email_path.rename(pack_dir / "email.txt")

    verification = tracker.verification_summary(job_id)
    links = tracker.links(job_id)
    row = next((r for r in tracker.list_jobs() if r["id"] == job_id), {})
    job_json = {
        "job": job.to_dict(),
        "status": row.get("status", ""),
        "score": row.get("score"),
        "policy_verdict": row.get("policy_verdict"),
        "company_verification": verification,
        "alternate_links": links,
        "fidelity_warnings": warnings,
    }
    (pack_dir / "job.json").write_text(json.dumps(job_json, indent=2), encoding="utf-8")

    route = verification.get("route") or job.url
    follow_up = ""
    fr = tracker.conn.execute("SELECT follow_up FROM jobs WHERE id=?", (job_id,)).fetchone()
    if fr and fr["follow_up"]:
        follow_up = time.strftime("%Y-%m-%d", time.localtime(fr["follow_up"]))
    checklist = [
        f"# Application checklist: {job.title} @ {job.company}", "",
        f"- Status: {row.get('status', 'new')}",
        f"- Application route: {route or 'none recorded - verify the official careers page'}",
        f"- Company verification: {verification.get('status', 'unknown')}",
    ]
    if verification.get("status") != "verified":
        checklist.append("  (not verified - confirm the employer through its official "
                         "site and LinkedIn before applying; see docs/company-verification.md)")
    checklist += [
        f"- Tailored CV: cv.pdf (Markdown source: cv.md)",
        f"- Email draft: email.txt",
        f"- Fit report: fit_report.md",
    ]
    if follow_up:
        checklist.append(f"- Follow up by: {follow_up}")
    checklist.append("")
    (pack_dir / "checklist.md").write_text("\n".join(checklist), encoding="utf-8")

    tracker.add_event(job_id, "pack", f"pack built at {pack_dir}")
    return {"job_id": job_id, "pack_dir": str(pack_dir),
            "files": sorted(p.name for p in pack_dir.iterdir()),
            "fidelity_warnings": warnings}

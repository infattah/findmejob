"""Standalone CV builder: one personalized CV per job ad, on demand.

Three entry points, all built only from master-CV facts:
- a tracked job (same strong-only gate as `findmejob tailor`)
- a pasted job ad (file or stdin), no search or tracker needed
- a general profile CV with no job targeting

The designed style is the default: navy band header, gold section
headings, optional photo. Text stays real and selectable, so the PDF
remains ATS-safe. The fidelity check flags anything that looks invented.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .models import JobPosting, Profile, make_job_id
from .render.pdf import jpeg_size, render_cv_pdf
from .tailor import check_fidelity, render_cv_markdown

STYLES = ("designed", "classic")


def job_from_ad(text: str, title: str = "", company: str = "") -> JobPosting:
    """Build a JobPosting from a pasted ad. It never enters the tracker."""
    job = JobPosting(title=title.strip(), company=company.strip(),
                     description=text.strip(), source="adhoc")
    job.id = make_job_id("adhoc", hashlib.sha1(text.encode("utf-8")).hexdigest(),
                         job.title, job.company)
    return job


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)[:80].strip("_")


def build_cv(profile: Profile, job: JobPosting | None, out_dir, *,
             style: str = "designed", photo: str | None = None) -> dict[str, Any]:
    """Render one CV (Markdown source + PDF) and run the fidelity check."""
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}; choose from {', '.join(STYLES)}")
    cv_md = render_cv_markdown(profile, job)
    warnings = check_fidelity(profile.all_facts_text(), cv_md)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    label = "General_CV" if job is None else (_safe(f"{job.company}_{job.title}") or f"job_{job.id}")
    base = _safe(profile.full_name) or "cv"
    md_path = out / f"{base}_{label}.md"
    pdf_path = out / f"{base}_{label}.pdf"
    notes: list[str] = []
    use_photo = None
    if photo and style == "designed":
        try:
            jpeg_size(Path(photo).read_bytes())
            use_photo = photo
        except (OSError, ValueError):
            notes.append(f"photo skipped ({photo}): not a readable JPEG")
    elif photo:
        notes.append("a photo only applies to the designed style - built without it")
    md_path.write_text(cv_md, encoding="utf-8")
    render_cv_pdf(profile, job, pdf_path, style=style, photo=use_photo)
    return {"cv": str(md_path), "pdf": str(pdf_path),
            "fidelity_warnings": warnings, "notes": notes}

"""CV tailoring and email drafting.

Hard rule: output may only contain facts present in the master CV.
Tailoring reorders and emphasizes; it never adds employers, titles,
metrics or skills. check_fidelity() flags anything that looks invented.
"""
from __future__ import annotations

import re

from .models import JobPosting, Profile


def _job_keywords(job: JobPosting) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9+#.]{2,}", job.search_text())}


def rank_skills(profile: Profile, job: JobPosting) -> list[str]:
    kw = _job_keywords(job)

    def rel(skill: str) -> int:
        tokens = skill.lower().split()
        return sum(1 for t in tokens if t in kw)

    return sorted(profile.skills, key=lambda s: (-rel(s), profile.skills.index(s)))


def rank_bullets(bullets: list[str], job: JobPosting) -> list[str]:
    kw = _job_keywords(job)

    def rel(bullet: str) -> int:
        return sum(1 for t in re.findall(r"[a-z0-9]+", bullet.lower()) if t in kw)

    return sorted(bullets, key=lambda b: (-rel(b), bullets.index(b)))


def render_cv_markdown(profile: Profile, job: JobPosting) -> str:
    lines: list[str] = [f"# {profile.full_name}", ""]
    contact = [p for p in [profile.email, profile.phone] if p]
    if contact:
        lines.append(" | ".join(contact))
        lines.append("")
    if profile.links:
        lines.append(" | ".join(f"{k}: {v}" for k, v in profile.links.items()))
        lines.append("")
    if profile.summary:
        lines += ["## Summary", "", profile.summary, ""]
    skills = rank_skills(profile, job)
    if skills:
        lines += ["## Skills", ""] + [f"- {s}" for s in skills] + [""]
    if profile.experiences:
        lines += ["## Experience", ""]
        for exp in profile.experiences:
            dates = " - ".join(p for p in [exp.start, exp.end] if p)
            head = f"### {exp.role} - {exp.company}"
            if dates:
                head += f" ({dates})"
            lines += [head, ""]
            lines += [f"- {b}" for b in rank_bullets(exp.bullets, job)]
            lines.append("")
    if profile.education:
        lines += ["## Education", ""]
        for edu in profile.education:
            lines.append(f"### {edu.degree} - {edu.school}" + (f" ({edu.year})" if edu.year else ""))
            lines.append("")
    return "\n".join(lines).strip() + "\n"


_NEW_TOKEN = re.compile(r"(?<![\w.])([A-Z][a-zA-Z0-9]{2,}|\d[\d,.]*%?)(?![\w%])")


def check_fidelity(master_text: str, tailored_text: str) -> list[str]:
    """Return suspicious tokens: capitalized words or numbers in the tailored
    output that never appear in the master CV. Heuristic, not proof."""
    master_tokens = set(_NEW_TOKEN.findall(master_text))
    suspicious: list[str] = []
    for tok in _NEW_TOKEN.findall(tailored_text):
        if tok not in master_tokens and tok not in suspicious:
            suspicious.append(tok)
    return suspicious


def draft_email(profile: Profile, job: JobPosting) -> tuple[str, str]:
    """Short, natural application email. The CV carries the detail."""
    first = (profile.full_name or "").split()[0] or "Hello"
    subject = f"Application: {job.title} - {profile.full_name}".strip()
    body_lines = [
        "Hi,",
        "",
        f"I'm applying for the {job.title} role at {job.company}. "
        "My CV is attached - it covers my background and results.",
    ]
    if profile.summary:
        body_lines.append("")
        body_lines.append(profile.summary.split(".")[0].strip() + ".")
    if profile.links:
        body_lines.append("")
        for name, url in list(profile.links.items())[:3]:
            body_lines.append(f"{name}: {url}")
    body_lines += ["", "Happy to answer any questions.", "", first]
    if profile.email:
        body_lines.append(profile.email)
    if profile.phone:
        body_lines.append(profile.phone)
    return subject, "\n".join(body_lines)

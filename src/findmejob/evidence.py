"""Evidence-based qualification.

Instead of one opaque keyword score, each requirement found in the job
description is checked against the candidate's master CV and labeled:

- strong:  direct evidence (a matching skill, or clear overlap with an
  experience bullet)
- partial: related evidence only (token overlap below the strong bar)
- missing: no evidence in the master CV

Deterministic and stdlib-only. Missing is a statement about the CV, not
about the person: it means "your master CV shows no evidence for this".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import JobPosting, Profile

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_REQ_HEADER = re.compile(
    r"(requirements|qualifications|what you'?ll need|what we'?re looking for|"
    r"who you are|about you|must[- ]haves?|you have|you bring)", re.IGNORECASE)
_SECTION_HEADER = re.compile(
    r"(responsibilities|what you'?ll do|about the role|about us|benefits|"
    r"perks|nice[- ]to[- ]haves?|preferred)", re.IGNORECASE)

_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "that",
    "this", "have", "has", "from", "who", "what", "ability", "strong",
    "experience", "experienced", "years", "year", "work", "working", "team",
    "skills", "skill", "knowledge", "plus", "etc", "role", "job", "must",
    "should", "least", "related", "field", "equivalent", "proven", "track",
    "record", "familiarity", "understanding", "including", "such", "like",
    "able", "etc.",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def extract_requirements(description: str, max_items: int = 12) -> list[str]:
    """Pull requirement-like lines out of a plain-text job description."""
    if not description:
        return []
    lines = [l.strip() for l in description.splitlines() if l.strip()]
    reqs: list[str] = []
    in_req = False
    for line in lines:
        if _REQ_HEADER.search(line) and len(line) < 120:
            in_req = True
            continue
        if _SECTION_HEADER.search(line) and len(line) < 120:
            in_req = False
            continue
        if _BULLET.match(line):
            text = _BULLET.sub("", line).strip()
            looks_like_req = in_req or any(
                m in text.lower()
                for m in ("year", "experience", "proficien", "degree", "skill",
                          "knowledge", "familiar", "expert", "fluent", "certif",
                          "bachelor", "master", "diploma", "ability to"))
            if looks_like_req and 12 <= len(text) <= 300:
                reqs.append(text)
        elif in_req and 12 <= len(line) <= 300:
            reqs.append(line)
    # fall back: when no structure was detected, treat "N+ years ..." sentences
    if not reqs:
        for sent in re.split(r"(?<=[.!?])\s+", description):
            if re.search(r"\d+\+?\s*years?", sent) and 12 <= len(sent) <= 300:
                reqs.append(sent.strip())
    seen: set[str] = set()
    out: list[str] = []
    for r in reqs:
        key = " ".join(sorted(_tokens(r)))[:200]
        if key and key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) >= max_items:
            break
    return out


@dataclass
class RequirementMatch:
    requirement: str
    status: str  # strong | partial | missing
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"requirement": self.requirement, "status": self.status,
                "evidence": self.evidence}


@dataclass
class FitReport:
    job_title: str
    company: str
    items: list[RequirementMatch] = field(default_factory=list)

    @property
    def strong(self) -> int:
        return sum(1 for i in self.items if i.status == "strong")

    @property
    def partial(self) -> int:
        return sum(1 for i in self.items if i.status == "partial")

    @property
    def missing(self) -> int:
        return sum(1 for i in self.items if i.status == "missing")

    def to_dict(self) -> dict[str, Any]:
        return {"job_title": self.job_title, "company": self.company,
                "strong": self.strong, "partial": self.partial,
                "missing": self.missing,
                "items": [i.to_dict() for i in self.items]}


def _match_one(requirement: str, profile: Profile) -> RequirementMatch:
    req_tokens = _tokens(requirement)
    if not req_tokens:
        return RequirementMatch(requirement, "partial",
                                ["requirement has no checkable keywords"])
    # 1) direct skill evidence
    for skill in profile.skills:
        skill_tokens = _tokens(skill)
        if skill_tokens and skill_tokens <= req_tokens:
            return RequirementMatch(requirement, "strong", [f"skill: {skill}"])
    # 2) experience-bullet evidence
    best: tuple[int, str] = (0, "")
    for exp in profile.experiences:
        for bullet in [exp.role + " " + exp.company] + exp.bullets:
            overlap = len(req_tokens & _tokens(bullet))
            if overlap > best[0]:
                best = (overlap, bullet.strip())
    ratio = best[0] / len(req_tokens)
    if (best[0] >= 3 and ratio >= 0.5) or (best[0] >= 2 and ratio >= 0.8):
        return RequirementMatch(requirement, "strong",
                                [f"experience: {best[1][:160]}"])
    if best[0] >= 2 and ratio >= 0.3:
        return RequirementMatch(requirement, "partial",
                                [f"related experience: {best[1][:160]}"])
    # 3) whole-CV fallback (summary, education)
    other = _tokens(profile.summary + " " + " ".join(
        f"{e.degree} {e.school}" for e in profile.education))
    if len(req_tokens & other) >= 2:
        return RequirementMatch(requirement, "partial", ["mentioned in CV summary/education"])
    return RequirementMatch(requirement, "missing", [])


def evaluate_requirements(profile: Profile, job: JobPosting) -> FitReport:
    report = FitReport(job_title=job.title, company=job.company)
    for req in extract_requirements(job.description):
        report.items.append(_match_one(req, profile))
    return report


def render_report_markdown(report: FitReport, score: int | None = None,
                           score_reasons: list[str] | None = None) -> str:
    lines = [f"# Fit report: {report.job_title} @ {report.company}", ""]
    if score is not None:
        lines.append(f"Keyword fit score: {score}/100")
    lines.append(
        f"Requirements: {report.strong} strong, {report.partial} partial, "
        f"{report.missing} missing (of {len(report.items)} found)")
    lines.append("")
    if score_reasons:
        lines += ["Score reasons:"] + [f"- {r}" for r in score_reasons] + [""]
    if not report.items:
        lines.append("No structured requirements found in the description; "
                     "rely on the keyword score and read the listing yourself.")
        lines.append("")
        return "\n".join(lines)
    icon = {"strong": "[strong]", "partial": "[partial]", "missing": "[MISSING]"}
    for item in report.items:
        lines.append(f"- {icon[item.status]} {item.requirement}")
        for ev in item.evidence:
            lines.append(f"    evidence: {ev}")
    lines.append("")
    lines.append("Missing means the master CV shows no evidence for the "
                 "requirement - it says nothing about the person.")
    lines.append("")
    return "\n".join(lines)

"""Deterministic, CV-grounded qualification evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import JobPosting, Profile

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_REQ_HEADER = re.compile(r"(requirements|qualifications|what you'?ll need|what we'?re looking for|who you are|about you|must[- ]haves?|you have|you bring)", re.I)
_SECTION_HEADER = re.compile(r"(responsibilities|what you'?ll do|about the role|about us|benefits|perks|nice[- ]to[- ]haves?|preferred)", re.I)
_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*(?:\+|plus)?\s*years?", re.I)
_HARD = re.compile(r"\b(must|required|requires?|minimum|at least|fluent|native|proficien(?:t|cy)|\d+\s*(?:\+|plus)?\s*years?|senior|head of|director|b2b|saas)\b", re.I)
_STOP = {"the", "and", "for", "with", "you", "your", "our", "are", "will", "that", "this", "have", "has", "from", "who", "what", "ability", "strong", "experience", "experienced", "years", "year", "work", "working", "team", "skills", "skill", "knowledge", "plus", "etc", "role", "job", "must", "should", "least", "related", "field", "equivalent", "proven", "track", "record", "familiarity", "understanding", "including", "such", "like", "able"}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def extract_requirements(description: str, max_items: int = 12) -> list[str]:
    if not description:
        return []
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    reqs: list[str] = []
    in_req = False
    for line in lines:
        if _REQ_HEADER.search(line) and len(line) < 120:
            in_req = True
            continue
        if _SECTION_HEADER.search(line) and len(line) < 120:
            in_req = False
            continue
        text = _BULLET.sub("", line).strip() if _BULLET.match(line) else line
        looks_like = in_req or any(x in text.lower() for x in ("year", "experience", "proficien", "degree", "skill", "knowledge", "familiar", "expert", "fluent", "native", "certif", "bachelor", "master", "diploma", "ability to", "required"))
        if looks_like and 12 <= len(text) <= 300:
            reqs.append(text)
    if not reqs:
        for sent in re.split(r"(?<=[.!?])\s+", description):
            if _YEARS.search(sent) and 12 <= len(sent) <= 300:
                reqs.append(sent.strip())
    seen: set[str] = set()
    out: list[str] = []
    for req in reqs:
        key = " ".join(sorted(_tokens(req)))[:200] or req.lower()
        if key not in seen:
            seen.add(key)
            out.append(req)
        if len(out) >= max_items:
            break
    return out


def is_hard_requirement(requirement: str) -> bool:
    return bool(_HARD.search(requirement))


@dataclass
class RequirementMatch:
    requirement: str
    status: str
    evidence: list[str] = field(default_factory=list)
    hard: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"requirement": self.requirement, "status": self.status, "evidence": self.evidence, "hard": self.hard}


@dataclass
class FitReport:
    job_title: str
    company: str
    items: list[RequirementMatch] = field(default_factory=list)

    @property
    def strong(self) -> int:
        return sum(i.status == "strong" for i in self.items)

    @property
    def partial(self) -> int:
        return sum(i.status == "partial" for i in self.items)

    @property
    def missing(self) -> int:
        return sum(i.status == "missing" for i in self.items)

    @property
    def hard_missing(self) -> int:
        return sum(i.hard and i.status != "strong" for i in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"job_title": self.job_title, "company": self.company, "strong": self.strong, "partial": self.partial, "missing": self.missing, "hard_missing": self.hard_missing, "items": [i.to_dict() for i in self.items]}


def _max_years(text: str) -> int | None:
    values = [int(x) for x in _YEARS.findall(text)]
    return max(values) if values else None


def _match_one(requirement: str, profile: Profile) -> RequirementMatch:
    hard = is_hard_requirement(requirement)
    req_years = _max_years(requirement)
    if req_years is not None:
        cv_years = _max_years(profile.all_facts_text())
        if cv_years is not None and cv_years >= req_years:
            return RequirementMatch(requirement, "strong", [f"CV explicitly states {cv_years}+ years"], hard)
        return RequirementMatch(requirement, "missing", [], hard)
    req_tokens = _tokens(requirement)
    if not req_tokens:
        return RequirementMatch(requirement, "missing" if hard else "partial", [], hard)
    for skill in profile.skills:
        skill_tokens = _tokens(skill)
        if skill_tokens and skill_tokens <= req_tokens:
            return RequirementMatch(requirement, "strong", [f"skill: {skill}"], hard)
    best: tuple[int, str] = (0, "")
    for exp in profile.experiences:
        for bullet in [exp.role + " " + exp.company] + exp.bullets:
            overlap = len(req_tokens & _tokens(bullet))
            if overlap > best[0]:
                best = (overlap, bullet.strip())
    ratio = best[0] / len(req_tokens)
    if (best[0] >= 3 and ratio >= .5) or (best[0] >= 2 and ratio >= .8):
        return RequirementMatch(requirement, "strong", [f"experience: {best[1][:160]}"], hard)
    if not hard and best[0] >= 2 and ratio >= .3:
        return RequirementMatch(requirement, "partial", [f"related experience: {best[1][:160]}"], hard)
    return RequirementMatch(requirement, "missing", [], hard)


def evaluate_requirements(profile: Profile, job: JobPosting) -> FitReport:
    report = FitReport(job.title, job.company)
    report.items = [_match_one(req, profile) for req in extract_requirements(job.description)]
    return report


def render_report_markdown(report: FitReport, score: int | None = None, score_reasons: list[str] | None = None) -> str:
    lines = [f"# Fit report: {report.job_title} @ {report.company}", ""]
    if score is not None:
        lines.append(f"Keyword fit score: {score}/100")
    lines += [f"Requirements: {report.strong} strong, {report.partial} partial, {report.missing} missing (of {len(report.items)} found)", f"Hard requirements not proven: {report.hard_missing}", ""]
    if score_reasons:
        lines += ["Score reasons:"] + [f"- {r}" for r in score_reasons] + [""]
    if not report.items:
        lines += ["No structured requirements found; read the listing before relying on the keyword score.", ""]
        return "\n".join(lines)
    icon = {"strong": "[strong]", "partial": "[partial]", "missing": "[MISSING]"}
    for item in report.items:
        lines.append(f"- {icon[item.status]}{' [HARD]' if item.hard else ''} {item.requirement}")
        lines += [f"    evidence: {ev}" for ev in item.evidence]
    lines += ["", "Missing means the master CV shows no evidence for the requirement - it says nothing about the person.", ""]
    return "\n".join(lines)

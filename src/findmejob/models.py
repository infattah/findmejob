"""Core data models. Stdlib only."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


def make_job_id(source: str, url: str, title: str, company: str) -> str:
    key = url.strip() or f"{source}:{company}:{title}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


@dataclass
class JobPosting:
    title: str
    company: str
    location: str = ""
    url: str = ""
    source: str = ""
    description: str = ""
    salary_text: str = ""
    posted_at: str = ""
    remote: bool = False
    # Optional source-provided facts. They are evidence with provenance, not guesses.
    apply_url: str = ""
    source_liveness: str = ""
    source_liveness_detail: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_job_id(self.source, self.url, self.title, self.company)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobPosting":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def search_text(self) -> str:
        return " ".join(
            [self.title, self.company, self.location, self.description, self.salary_text]
        ).lower()


@dataclass
class Experience:
    role: str
    company: str
    start: str = ""
    end: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class Education:
    degree: str
    school: str
    year: str = ""


@dataclass
class Profile:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    headline: str = ""
    summary: str = ""
    links: dict[str, str] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    experiences: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    raw_text: str = ""

    def all_facts_text(self) -> str:
        parts = [self.full_name, self.headline, self.summary, " ".join(self.skills)]
        for exp in self.experiences:
            parts.append(f"{exp.role} {exp.company} " + " ".join(exp.bullets))
        for edu in self.education:
            parts.append(f"{edu.degree} {edu.school} {edu.year}")
        parts.append(self.raw_text)
        return " ".join(p for p in parts if p)

    def skill_tokens(self) -> set[str]:
        return {s.strip().lower() for s in self.skills if s.strip()}


@dataclass
class PolicyResult:
    verdict: str  # "pass" | "review" | "block"
    reasons: list[str] = field(default_factory=list)


@dataclass
class FitScore:
    score: int  # 0-100
    reasons: list[str] = field(default_factory=list)

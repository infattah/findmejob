"""Deterministic fit scoring. No LLM required."""
from __future__ import annotations

import re

from .models import FitScore, JobPosting, Profile

_TOKEN = re.compile(r"[a-z][a-z0-9+#.]{1,}")

_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "that",
    "this", "have", "has", "from", "who", "what", "job", "role", "work",
    "team", "years", "year", "experience", "skills", "ability", "strong",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def _target_phrase_in_title(keyword: str, title: str) -> bool:
    """Match target tokens in order, allowing a short inserted specialism."""
    target = _TOKEN.findall(keyword.lower())
    words = _TOKEN.findall(title.lower())
    if not target:
        return False
    pos = -1
    for token in target:
        try:
            found = words.index(token, pos + 1)
        except ValueError:
            return False
        if pos >= 0 and found - pos - 1 > 3:
            return False
        pos = found
    return True


def score_fit(profile: Profile, job: JobPosting, role_keywords: list[str] | None = None) -> FitScore:
    reasons: list[str] = []
    job_tokens = _tokens(job.search_text())
    title_tokens = _tokens(job.title)

    skills = profile.skill_tokens()
    skill_hits = sorted(
        s for s in skills
        if _tokens(s) and (_tokens(s) & job_tokens)
    )
    skill_score = min(40, 8 * len(skill_hits))
    if skill_hits:
        reasons.append("skills matched: " + ", ".join(skill_hits[:8]))

    # A single generic shared word (for example "automation" in a content-
    # operations title) must not turn an adjacent role into a target-role hit.
    # Require the complete normalized target phrase in the title.
    kw_hits = sum(1 for kw in role_keywords or [] if _target_phrase_in_title(kw, job.title))
    title_score = min(30, 15 * kw_hits)
    if kw_hits:
        reasons.append(f"title matches {kw_hits} target role keyword(s)")

    profile_tokens = _tokens(profile.all_facts_text())
    overlap = job_tokens & profile_tokens
    ctx_score = min(20, len(overlap) // 3)
    if ctx_score:
        reasons.append(f"{len(overlap)} shared context terms")

    loc_score = 0
    if job.remote:
        loc_score = 10
        reasons.append("remote friendly")
    elif job.location:
        loc_score = 5

    score = min(100, skill_score + title_score + ctx_score + loc_score)
    if role_keywords and not kw_hits:
        # Keep adjacent discoveries visible, but below the default actionable
        # threshold. A reviewer may still inspect them; they are not promoted
        # from generic skill overlap alone.
        score = min(score, 44)
        reasons.append("title is adjacent to, not a direct match for, target roles")
    if not reasons:
        reasons.append("little overlap between the role and the master CV")
    return FitScore(score=score, reasons=reasons)

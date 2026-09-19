"""Eligibility and values policy checks.

Policy is yours: salary floor, locations, sectors to exclude, titles to skip.
A job is "pass", "review" (a human should look), or "block".

Salary floors are compared in the policy's own currency. With
policy.exchange_rates configured ({currency: units of base per 1 unit}),
any stated salary is annualized and converted strictly. Unknown currency,
unknown pay period, or a missing exchange rate always requires review.
"""
from __future__ import annotations

from typing import Any

from .models import JobPosting, PolicyResult
from .salary import normalize, parse_salary

def check_job(job: JobPosting, policy: dict[str, Any]) -> PolicyResult:
    reasons: list[str] = []
    text = job.search_text()
    title = job.title.lower()
    location = (job.location or "").lower()

    for word in policy.get("sector_exclusions", []) or []:
        if word.lower() in text:
            return PolicyResult("block", [f"excluded sector keyword: {word}"])

    for word in policy.get("title_exclude", []) or []:
        if word.lower() in title:
            return PolicyResult("block", [f"excluded title keyword: {word}"])

    include = [l.lower() for l in policy.get("locations_include", []) or []]
    exclude = [l.lower() for l in policy.get("locations_exclude", []) or []]
    if any(x in location for x in exclude):
        return PolicyResult("block", [f"excluded location: {job.location}"])
    # Remote describes work mode, not geography or work authorization. A remote
    # listing still has to prove that its hiring location matches the profile.
    geo_include = [x for x in include if x not in {"remote", "anywhere", "worldwide"}]
    if geo_include:
        if not location or location in {"remote", "anywhere", "worldwide"}:
            reasons.append("remote role has no confirmed hiring location in include list")
        elif not any(x in location for x in geo_include):
            reasons.append(f"location '{job.location}' not in include list")

    floor = int(policy.get("salary_floor") or 0)
    if floor > 0:
        reasons.extend(_salary_reasons(job, policy, floor))

    verdict = "pass" if not reasons else "review"
    return PolicyResult(verdict, reasons)


def _salary_reasons(job: JobPosting, policy: dict[str, Any], floor: int) -> list[str]:
    base = (policy.get("currency") or "").upper()
    rates = {k.upper(): float(v) for k, v in (policy.get("exchange_rates") or {}).items()}
    salary = parse_salary(job.salary_text or "")
    if salary is None:
        return ["salary not stated; cannot verify floor"]
    norm = normalize(salary, base, rates)
    if norm.converted and norm.annual_min is not None:
        shown = int(norm.annual_min)
        if shown < floor:
            return [f"salary {shown} {base or salary.currency}/yr below floor {floor}"]
        return []
    # Comparison is load-bearing: raw magnitudes across currencies or pay
    # periods are not comparable. Never let an unnormalizable salary pass.
    detail = norm.notes[-1] if norm.notes else "salary could not be normalized"
    return [f"salary requires review; cannot verify floor {floor} {base}: {detail}"]

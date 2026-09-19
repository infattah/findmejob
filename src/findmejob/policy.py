"""Eligibility and values policy checks.

Policy is yours: salary floor, locations, sectors to exclude, titles to skip.
A job is "pass", "review" (a human should look), or "block".

Salary floors are compared in the policy's own currency. With
policy.exchange_rates configured ({currency: units of base per 1 unit}),
any stated salary is annualized and converted strictly. Unknown currency,
unknown pay period, or a missing exchange rate always requires review.
"""
from __future__ import annotations

import re
from typing import Any

from .models import JobPosting, PolicyResult
from .salary import normalize, parse_salary

_SALARY_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.IGNORECASE)


def parse_salary_floor(text: str) -> int | None:
    """Best-effort lower bound of a salary range, normalized to a yearly figure."""
    if not text:
        return None
    nums: list[float] = []
    for m in _SALARY_NUM.finditer(text):
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000
        nums.append(val)
    if not nums:
        return None
    big = [n for n in nums if n > 100]
    low = min(big) if big else min(nums)
    text_low = text.lower()
    if ("month" in text_low or "/mo" in text_low) and low < 200000:
        low *= 12
    elif low < 1000:  # looks like an hourly rate
        low *= 2080
    return int(low)


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
    if include and location and not job.remote:
        if not any(x in location for x in include):
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

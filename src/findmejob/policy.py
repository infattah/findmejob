"""Eligibility and values policy checks.

Policy is yours: salary floor, locations, sectors to exclude, titles to skip.
A job is "pass", "review" (a human should look), or "block".
"""
from __future__ import annotations

import re
from typing import Any

from .models import JobPosting, PolicyResult

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
        low = parse_salary_floor(job.salary_text or "")
        if low is not None and low < floor:
            reasons.append(f"salary {low} below floor {floor}")
        elif low is None:
            reasons.append("salary not stated; cannot verify floor")

    verdict = "pass" if not reasons else "review"
    return PolicyResult(verdict, reasons)

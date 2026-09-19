"""Eligibility and values policy checks.

Policy is yours: salary floor, locations, sectors to exclude, titles to skip.
A job is "pass", "review" (a human should look), or "block".

Sector screening uses employer/business and role context. It deliberately ignores
standard legal/self-identification boilerplate and does not treat a customer's
industry as the employer's industry.

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

# Common starts of US equal-opportunity and voluntary self-ID copy. Everything
# after one of these headings is compliance text, not employer-sector evidence.
_BOILERPLATE_START = re.compile(
    r"(?im)^\s*(?:equal employment opportunity|equal opportunity employer|"
    r"voluntary self-identification|self-identification of disability|"
    r"eeo(?:-| )?1|diversity,? equity and inclusion)\b"
)

# Configured phrases remain the source of policy. These aliases only recognize
# ordinary descriptions of the same configured restricted business concept.
_SECTOR_CONCEPTS: dict[str, tuple[str, ...]] = {
    "forex trading": ("foreign exchange", "fx", "cross-border payment", "cross border payment",
                      "currency exchange", "currency conversion"),
    "capital markets": ("investment platform", "wealth management", "digital wealth",
                        "brokerage", "trading platform"),
    "wealth": ("wealth management", "digital wealth", "investment platform"),
    "hotel": ("hotel", "resort", "lodging", "accommodation"),
    "hospitality": ("hotel", "resort", "lodging", "hospitality"),
}
_TECH_PROVIDER = re.compile(
    r"\b(?:software|saas|platform|technology|fintech|payments?|point[- ]of[- ]sale|pos|app)\b",
    re.I,
)
_CUSTOMER_CONTEXT = re.compile(
    r"\b(?:for|serving|serves|helping|used by|customers? (?:are|include)|clients? (?:are|include))\s+"
    r"(?:the\s+)?(?:restaurants?|hospitality|hotels?)\b",
    re.I,
)


def _business_text(job: JobPosting) -> str:
    """Return context fit for sector classification, excluding legal boilerplate."""
    description = job.description or ""
    match = _BOILERPLATE_START.search(description)
    if match:
        description = description[:match.start()]
    return " ".join((job.company, job.title, description)).lower()


def _sector_match(job: JobPosting, configured: str) -> str | None:
    needle = configured.strip().lower()
    if not needle:
        return None
    text = _business_text(job)
    candidates = (needle,) + _SECTOR_CONCEPTS.get(needle, ())
    for phrase in candidates:
        if not re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text):
            continue
        # A technology provider mentioning hospitality/restaurants as its
        # customer market is not itself a hotel or alcohol-serving employer.
        if needle in {"hotel", "hospitality"} and _TECH_PROVIDER.search(text):
            around = re.compile(
                r"(?:" + _CUSTOMER_CONTEXT.pattern + r").{0,100}\b" + re.escape(phrase) +
                r"\b|\b" + re.escape(phrase) + r"\b.{0,100}(?:" + _CUSTOMER_CONTEXT.pattern + r")",
                re.I,
            )
            if _CUSTOMER_CONTEXT.search(text) or around.search(text):
                continue
        return phrase
    return None


def check_job(job: JobPosting, policy: dict[str, Any]) -> PolicyResult:
    reasons: list[str] = []
    title = job.title.lower()
    location = (job.location or "").lower()

    for word in policy.get("sector_exclusions", []) or []:
        matched = _sector_match(job, str(word))
        if matched:
            detail = str(word) if matched == str(word).lower() else f"{word} (matched business context: {matched})"
            return PolicyResult("block", [f"excluded sector: {detail}"])

    for word in policy.get("title_exclude", []) or []:
        if word.lower() in title:
            return PolicyResult("block", [f"excluded title keyword: {word}"])

    include = [l.lower() for l in policy.get("locations_include", []) or []]
    exclude = [l.lower() for l in policy.get("locations_exclude", []) or []]
    if any(x in location for x in exclude):
        return PolicyResult("block", [f"excluded location: {job.location}"])
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
    detail = norm.notes[-1] if norm.notes else "salary could not be normalized"
    return [f"salary requires review; cannot verify floor {floor} {base}: {detail}"]

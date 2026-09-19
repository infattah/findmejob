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

# Recognizable starts of equal-opportunity and voluntary self-ID copy. These
# markers are intentionally not line-anchored: ATS pages often append the legal
# tail to the last paragraph instead of giving it a heading.
_BOILERPLATE_START = re.compile(
    r"(?i)\b(?:we are (?:an )?equal opportunity employer|equal employment opportunity|"
    r"equal opportunity employer|voluntary self[- ]identification(?: of disability)?|"
    r"self[- ]identification of disability|disability categories include|"
    r"eeo(?:-| )?1(?: voluntary)? self[- ]identification)\b"
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
_PROVIDER_CUSTOMER_CONTEXT = re.compile(
    r"\b(?:platform|software|saas|technology|fintech|payments?|point[- ]of[- ]sale|pos|app)\b"
    r".{0,120}\b(?:for|serving|serves|helps?|used by|customers? (?:are|include)|"
    r"clients? (?:are|include))\s+(?:the\s+)?(?:restaurants?|hospitality(?: businesses| operators| customers)?|hotels?)\b",
    re.I,
)
_FOREX_RESTRICTED_PHRASE = (
    r"\b(?:foreign exchange|fx|cross[- ]border payments?|currency (?:exchange|conversion))\b"
)
_FOREX_BUSINESS_NOUN = r"\b(?:compan(?:y|ies)|business(?:es)?|fintechs?|platforms?|providers?|services?|networks?)\b"
_FOREX_BUSINESS_CONTEXT = re.compile(
    # business noun + offering verb + restricted phrase
    r"\b(?:company|business|fintech|platform|provider|service|network|we|our)\b.{0,100}"
    r"\b(?:provides?|offers?|speciali[sz](?:es|ing)|enables?|facilitates?|powers?|"
    r"operates?|delivers?|built for|focused on)\b.{0,80}"
    + _FOREX_RESTRICTED_PHRASE + "|"
    # business noun + for/of + restricted phrase ("provider for foreign exchange")
    + _FOREX_BUSINESS_NOUN + r"\s+(?:for|of)\s+" + _FOREX_RESTRICTED_PHRASE + "|"
    # restricted phrase + business noun ("foreign exchange provider")
    + _FOREX_RESTRICTED_PHRASE
    + r".{0,80}\b(?:company|business|fintech|platform|provider|service|network)\b",
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
    identity = " ".join((job.company, job.title)).lower()
    candidates = (needle,) + _SECTOR_CONCEPTS.get(needle, ())
    if needle == "forex trading":
        for phrase in candidates:
            pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
            if re.search(pattern, identity) or (re.search(pattern, text) and _FOREX_BUSINESS_CONTEXT.search(text)):
                return phrase
        return None
    direct_hotel_identity = bool(re.search(r"\b(?:hotel|resort|lodging|hospitality)\b", identity))
    provider_customer = bool(_TECH_PROVIDER.search(text) and _PROVIDER_CUSTOMER_CONTEXT.search(text))
    for phrase in candidates:
        if not re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text):
            continue
        if needle in {"hotel", "hospitality"} and not direct_hotel_identity and provider_customer:
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

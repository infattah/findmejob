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
    r"eeo(?:-| )?1(?: voluntary)? self[- ]identification|"
    r"(?:reasonable )?accommodation request|request (?:a |an )?reasonable accommodation|"
    r"accommodation (?:because of|due to) (?:a )?disabilit(?:y|ies))\b"
)

# Configured phrases remain the source of policy. These aliases only recognize
# ordinary descriptions of the same configured restricted business concept.
_SECTOR_CONCEPTS: dict[str, tuple[str, ...]] = {
    "forex trading": ("foreign exchange", "fx", "cross-border payment", "cross border payment",
                      "currency exchange", "currency conversion", "remittance",
                      "payment transaction", "payroll services", "corporate payments", "card services"),
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
    r"\b(?:foreign exchange|fx|cross[- ]border payments?|currency (?:exchange|conversion)|"
    r"remittances?|payment transactions?|payment processing|payroll services?|corporate payments?|card services?)\b"
)
_FOREX_BUSINESS_NOUN = r"\b(?:compan(?:y|ies)|business(?:es)?|fintechs?|platforms?|providers?|services?|networks?)\b"
_PAYMENT_TRANSACTION_ANALYTICS = re.compile(
    # Neutral analysis of transactions, in either natural word order. Keep the
    # transaction object out of provider classification without weakening real
    # processing/facilitation signals.
    r"\b(?:payment transactions?\s+(?:analytics?|analysis|reporting|measurement|metrics?|insights?|data)"
    r"|(?:analytics?|analysis|reporting|measurement|metrics?|insights?|data)\s+"
    r"(?:for|of|into|on|about)\s+payment transactions?)\b",
    re.I,
)
_PAYMENT_CUSTOMER_PROCESSING = re.compile(
    r"\b(?:clients?|customers?|merchants?|retailers?)\b.{0,50}"
    r"\bprocess(?:es|ing)?\s+payment transactions?\b",
    re.I,
)
_FOREX_BUSINESS_CONTEXT = re.compile(
    # business noun + offering verb + restricted phrase
    r"\b(?:company|business|fintech|platform|provider|service|network|we|our)\b.{0,100}"
    r"\b(?:provides?|offers?|speciali[sz](?:es|ing)|enables?|facilitates?|powers?|"
    r"operates?|delivers?|process(?:es|ing)?|built for|focused on)\b.{0,80}"
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
            # Keep the configured alias lookup aligned with the contextual matcher:
            # cross-border payment(s) is one business concept across hyphenation
            # and singular/plural wording.
            if phrase in {"cross-border payment", "cross border payment"}:
                pattern = r"(?<![a-z0-9])cross[- ]border payments?(?![a-z0-9])"
            elif phrase == "remittance":
                pattern = r"(?<![a-z0-9])remittances?(?![a-z0-9])"
            elif phrase == "payment transaction":
                pattern = r"(?<![a-z0-9])(?:payment transactions?|payment processing)(?![a-z0-9])"
            else:
                pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
            # A job title can name a product without identifying the employer's
            # business. Require company identity or grounded business prose for
            # payment-transaction aliases.
            identity_match = re.search(pattern, identity)
            if phrase == "payment transaction":
                company_identity = re.search(pattern, job.company.lower())
                # Analytics/reporting *about* transactions is neutral. Remove
                # that object before provider-context recognition so "provide
                # payment transaction analytics" cannot become "provide payment
                # transactions".
                business_text = _PAYMENT_TRANSACTION_ANALYTICS.sub("transaction analytics", text)
                business_text = _PAYMENT_CUSTOMER_PROCESSING.sub("customer activity", business_text)
                contextual = re.search(pattern, business_text) and _FOREX_BUSINESS_CONTEXT.search(business_text)
                if company_identity or contextual:
                    return phrase
            elif identity_match or (re.search(pattern, text) and _FOREX_BUSINESS_CONTEXT.search(text)):
                return phrase
        return None
    provider_customer = bool(_TECH_PROVIDER.search(text) and _PROVIDER_CUSTOMER_CONTEXT.search(text))
    hotel_identity_pattern = r"\b(?:hotels?|resorts?|lodging|hospitality)\b"
    company_hotel_identity = bool(re.search(hotel_identity_pattern, job.company, re.I))
    title_hotel_identity = bool(re.search(hotel_identity_pattern, job.title, re.I))
    # A title can name the provider's customer vertical (for example, "Hotel
    # Technology Product Manager") without identifying the employer as a hotel.
    # Only waive title identity when both the title and employer prose ground a
    # technology/provider-for-hotels context. Company identity always wins.
    title_provider_vertical = bool(
        title_hotel_identity and _TECH_PROVIDER.search(job.title) and provider_customer
    )
    direct_hotel_identity = company_hotel_identity or (
        title_hotel_identity and not title_provider_vertical
    )
    for phrase in candidates:
        if phrase in {"hotel", "resort"}:
            phrase_pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"s?(?![a-z0-9])"
        else:
            phrase_pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
        if not re.search(phrase_pattern, text):
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

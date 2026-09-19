"""Cross-source deduplication.

The same role appears on an ATS, an aggregator and the company careers page
with different URLs. Two signals, in priority order:

1. Canonical URL: tracking parameters, scheme, www and case removed.
2. Signature: normalized (company, title, location). Company suffixes
   (Ltd, LLC, Inc, DMCC...) and punctuation are stripped; a missing
   location on either side is treated as unknown, not as a mismatch.

A duplicate is never dropped silently: the surviving record keeps the
alternate source and URL so every verified route stays reachable.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import JobPosting

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "src", "fbclid", "gclid", "mc_cid", "mc_eid", "trk",
    "tracking_id", "gh_jid", "lever-source",
}

_COMPANY_SUFFIXES = re.compile(
    r"\b(ltd|limited|llc|l\.l\.c|inc|incorporated|gmbh|sarl|s\.a\.r\.l|dmcc|"
    r"fz-llc|fz llc|fze|fzco|pjsc|psc|llp|plc|pty|pte|co|company|corp|"
    r"corporation|group|holdings?)\b\.?", re.IGNORECASE)

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS))
    path = re.sub(r"/+$", "", parts.path or "")
    return urlunsplit(("", host, path.lower(), query, ""))


def _norm(text: str) -> str:
    return _WS.sub(" ", _NON_ALNUM.sub("", text.lower())).strip()


def norm_company(company: str) -> str:
    return _WS.sub(" ", _COMPANY_SUFFIXES.sub("", _norm(company))).strip()


def norm_location(location: str) -> str:
    full = _norm(location)
    if full in {"remote", "anywhere", "worldwide", "global"}:
        return "remote"
    # keep the first segment: "Dubai, UAE" and "Dubai" must match
    return _norm(location.split(",")[0])


def signature(job: JobPosting) -> tuple[str, str, str]:
    return (norm_company(job.company), _norm(job.title), norm_location(job.location))


def signatures_match(a: tuple[str, str, str], b: tuple[str, str, str]) -> bool:
    if a[0] != b[0] or a[1] != b[1]:
        return False
    if a[0] == "" or a[1] == "":
        return False  # never merge records missing company or title
    if a[2] and b[2] and a[2] != b[2]:
        return False
    return True


def find_duplicate(job: JobPosting, candidates: Iterable[JobPosting]) -> Optional[JobPosting]:
    """Return the first candidate that is the same role, or None."""
    url = canonical_url(job.url)
    sig = signature(job)
    for other in candidates:
        if url and canonical_url(other.url) == url:
            return other
        if signatures_match(sig, signature(other)):
            return other
    return None


def dedupe_batch(jobs: list[JobPosting]) -> tuple[list[JobPosting], list[tuple[JobPosting, JobPosting]]]:
    """Split a fetched batch into (unique, duplicates as (kept, dupe) pairs)."""
    unique: list[JobPosting] = []
    dupes: list[tuple[JobPosting, JobPosting]] = []
    for job in jobs:
        kept = find_duplicate(job, unique)
        if kept is None:
            unique.append(job)
        else:
            dupes.append((kept, job))
    return unique, dupes

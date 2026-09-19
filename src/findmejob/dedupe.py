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
from difflib import SequenceMatcher
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


def _description_similarity(a: str, b: str) -> float:
    def clean(text: str) -> str:
        return " ".join(_norm(text).split())
    left, right = clean(a), clean(b)
    if len(left) < 120 or len(right) < 120:
        return 0.0
    return min(SequenceMatcher(None, left, right, autojunk=False).ratio(),
               SequenceMatcher(None, right, left, autojunk=False).ratio())


_JOB_CUE = re.compile(
    r"(?i)\b(?:own|lead|manage|build|execute|optimi[sz]e|analy[sz]e|report|drive|launch|plan|deliver|"
    r"responsible|campaign|pipeline|attribution|cac|roas|retail|cybersecurity|channel partner|"
    r"google ads|meta ads|paid media|loyalty|promotion|franchise|field event|quota|crm|software|engineering)\b")
_BOILERPLATE = re.compile(
    r"(?i)\b(?:equal opportunity|application guidance|interview support|recruiter supports|"
    r"leading clients|benefits package|privacy policy|terms and conditions|apply now)\b")


def _job_specific_tokens(text: str) -> set[str]:
    """Keep duty/domain language and discard ordinary recruiter template prose."""
    pieces = re.split(r"(?<=[.!?])\s+|[\n;]+", text or "")
    specific = [p for p in pieces if _JOB_CUE.search(p) and not _BOILERPLATE.search(p)]
    return set().union(*(_norm(p).split() for p in specific)) if specific else set()


def _specific_similarity(a: str, b: str) -> float:
    left, right = _job_specific_tokens(a), _job_specific_tokens(b)
    if min(len(left), len(right)) < 8:
        return 0.0
    return len(left & right) / len(left | right)


def _wrapper_duplicate(job: JobPosting, other: JobPosting) -> bool:
    # Different requisitions are ambiguous even when employer/title/location match.
    # Merge wrappers only when job-specific duties/domain are nearly identical;
    # recruiter boilerplate is explicitly excluded from this evidence.
    a, b = signature(job), signature(other)
    if not a[1] or a[1] != b[1]: return False
    if a[2] and b[2] and a[2] != b[2]: return False
    return (_description_similarity(job.description, other.description) >= .90
            and _specific_similarity(job.description, other.description) >= .88)


def find_duplicate(job: JobPosting, candidates: Iterable[JobPosting]) -> Optional[JobPosting]:
    """Return the first candidate that is the same role, or None."""
    urls = {canonical_url(job.url), canonical_url(getattr(job, "apply_url", ""))} - {""}
    sig = signature(job)
    for other in candidates:
        other_urls = {canonical_url(other.url), canonical_url(getattr(other, "apply_url", ""))} - {""}
        if urls & other_urls:
            return other
        if _wrapper_duplicate(job, other):
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

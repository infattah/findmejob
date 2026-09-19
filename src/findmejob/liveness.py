"""Listing liveness checks.

A fetched posting is a lead, not proof the role is still open. This pass
visits the listing URL and marks it alive, expired or unknown. It is
deliberately conservative: only a clear 404/410 or an explicit expiry
message marks a listing expired; anything ambiguous stays unknown so real
roles are never dropped on a hunch.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import json
import time
from typing import Callable, Optional

from .httpcache import USER_AGENT

ALIVE_MARKERS = [
    "apply for this job", "apply now", "submit application",
    "application form", "job application",
]

EXPIRY_MARKERS = [
    "no longer available", "no longer accepting", "job has expired",
    "this job is no longer", "position has been filled", "job not found",
    "page not found", "listing has expired", "job is closed",
    "applications for this position have closed", "applications for this role have closed",
    "applications for this job have closed", "applications for the position have closed",
    "applications for the role have closed", "applications for the job have closed",
    "applications have closed", "applications are now closed", "applications are closed",
    "applications closed", "vacancy has expired", "vacancy expired",
    "job has been removed", "this position is no longer active",
]

Opener = Callable[[str, int], tuple[int, str]]


def default_opener(url: str, timeout: int) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # cap the read: expiry banners live near the top
        return resp.status, resp.read(200_000).decode("utf-8", errors="replace")


def check_listing(url: str, opener: Optional[Opener] = None,
                  timeout: int = 15) -> tuple[str, str]:
    """Return (status, detail): status is alive | expired | unknown."""
    if not url:
        return "unknown", "no URL recorded"
    opener = opener or default_opener
    try:
        status, body = opener(url, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return "expired", f"HTTP {exc.code}"
        return "unknown", f"HTTP {exc.code}"
    except Exception as exc:  # DNS, TLS, timeout - say nothing about the job
        return "unknown", f"check failed: {exc.__class__.__name__}"
    if status in (404, 410):
        return "expired", f"HTTP {status}"
    if status >= 400:
        return "unknown", f"HTTP {status}"
    low = body.lower()
    for marker in EXPIRY_MARKERS:
        if marker in low:
            return "expired", f"page says: {marker}"
    if status == 200 and len(re.sub(r"\s+", "", low)) < 200:
        return "unknown", "page content too short to confirm"
    for marker in ALIVE_MARKERS:
        if marker in low:
            return "alive", f"page says: {marker}"
    return "unknown", f"HTTP {status} only; no explicit open/apply evidence"


def _ashby_refresh(job, json_opener=None, timeout: int = 15) -> tuple[str, str]:
    """Re-read an Ashby board for verification; persisted hints are never perpetual."""
    board = str(getattr(job, "source", "")).partition(":")[2]
    if not board:
        return "unknown", "Ashby source board unavailable"
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
    try:
        if json_opener:
            data = json_opener(url, timeout)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read(2_000_000).decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return "unknown", f"Ashby posting API HTTP {exc.code}"
    except Exception as exc:
        return "unknown", f"Ashby posting API check failed: {exc.__class__.__name__}"
    if not isinstance(data, dict) or set(data) == {"error"}:
        return "unknown", "Ashby posting API: malformed or error payload"
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(item, dict) for item in jobs):
        return "unknown", "Ashby posting API: malformed jobs payload"
    canonical = getattr(job, "url", "").rstrip("/").lower()
    if not canonical:
        return "unknown", "Ashby posting API: tracked job URL unavailable"
    match = next((j for j in jobs
                  if (j.get("jobUrl") or "").rstrip("/").lower() == canonical), None)
    if match is None:
        return "expired", "Ashby posting API: job no longer listed on board"
    if match.get("isListed") is False:
        return "expired", "Ashby posting API: isListed=false"
    if match.get("isListed") is True and match.get("applyUrl"):
        return "alive", "Ashby posting API: isListed=true and applyUrl present"
    return "unknown", "Ashby posting API: listing state or applyUrl missing"


def check_job_liveness(job, opener: Optional[Opener] = None, timeout: int = 15,
                       json_opener=None, now: Optional[float] = None,
                       hint_max_age: int = 300) -> tuple[str, str]:
    """Use fresh structured evidence; verification refreshes Ashby instead of freezing hints."""
    now = time.time() if now is None else now
    hint = getattr(job, "source_liveness", "")
    detail = getattr(job, "source_liveness_detail", "")
    checked = float(getattr(job, "source_liveness_checked_at", 0) or 0)
    if str(getattr(job, "source", "")).startswith("ashby:"):
        if (hint in {"alive", "expired"} and detail and checked
                and 0 <= now - checked <= hint_max_age):
            return hint, detail
        return _ashby_refresh(job, json_opener=json_opener, timeout=timeout)
    return check_listing(getattr(job, "url", ""), opener=opener, timeout=timeout)

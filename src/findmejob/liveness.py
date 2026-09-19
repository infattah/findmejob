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
    "applications have closed",
    "applications closed", "vacancy has expired", "vacancy expired",
    "job has been removed",
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

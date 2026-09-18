"""Workable public widget API. Endpoint shape varies by account; adjust if a
board stops responding. Tests run offline against a fixture."""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_json, strip_html


class WorkableSource:
    def __init__(self, spec: dict[str, Any]):
        self.subdomain = spec["subdomain"]
        self.name = f"workable:{self.subdomain}"

    def fetch(self) -> list[JobPosting]:
        data = http_json(
            f"https://apply.workable.com/api/v1/widget/accounts/{self.subdomain}"
        )
        jobs = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {})
            loc_text = loc.get("locationName", "") if isinstance(loc, dict) else str(loc or "")
            jobs.append(JobPosting(
                title=(j.get("title") or "").strip(),
                company=self.subdomain,
                location=loc_text,
                url=j.get("url", "") or f"https://apply.workable.com/{self.subdomain}/",
                source=self.name,
                description=strip_html(j.get("description", "") or ""),
                remote="remote" in loc_text.lower(),
            ))
        return jobs

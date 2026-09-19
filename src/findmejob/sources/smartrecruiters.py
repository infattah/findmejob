"""SmartRecruiters public API: https://api.smartrecruiters.com/v1/companies/{company}/postings"""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_json


class SmartRecruitersSource:
    def __init__(self, spec: dict[str, Any]):
        self.company = spec["company"]
        self.name = f"smartrecruiters:{self.company}"

    def fetch(self) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        offset = 0
        while True:  # the API pages 100 at a time; stop at the last page
            data = http_json(
                f"https://api.smartrecruiters.com/v1/companies/{self.company}"
                f"/postings?limit=100&offset={offset}"
            )
            batch = data.get("content", [])
            for j in batch:
                loc = j.get("location") or {}
                place = ", ".join(p for p in [loc.get("city", ""), loc.get("country", "")] if p)
                jobs.append(JobPosting(
                    title=(j.get("name") or "").strip(),
                    company=self.company,
                    location=place,
                    url=(j.get("applyUrl") or j.get("ref") or ""),
                    source=self.name,
                    posted_at=j.get("releasedDate", "") or "",
                    remote=bool(loc.get("remote")) or "remote" in place.lower(),
                ))
            if len(batch) < 100:
                break
            offset += 100
        return jobs

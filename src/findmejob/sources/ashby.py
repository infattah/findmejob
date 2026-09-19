"""Ashby public posting API: https://api.ashbyhq.com/posting-api/job-board/{board}"""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_json, strip_html


class AshbySource:
    def __init__(self, spec: dict[str, Any]):
        self.board = spec["board"]
        self.name = f"ashby:{self.board}"

    def fetch(self) -> list[JobPosting]:
        data = http_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{self.board}"
            "?includeCompensation=true"
        )
        jobs = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "") or j.get("locationName", "")
            comp = j.get("compensation") or {}
            salary = comp.get("compensationTierSummary", "") or ""
            desc = j.get("descriptionPlain", "") or strip_html(j.get("descriptionHtml", "") or "")
            jobs.append(JobPosting(
                title=(j.get("title") or "").strip(),
                company=self.board,
                location=loc,
                url=j.get("jobUrl", "") or "",
                source=self.name,
                description=desc,
                salary_text=salary,
                posted_at=j.get("publishedAt", "") or "",
                remote=bool(j.get("isRemote")) or "remote" in loc.lower(),
            ))
        return jobs

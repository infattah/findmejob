"""Remotive free public API: https://remotive.com/api/remote-jobs"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..models import JobPosting
from .base import http_json, strip_html


class RemotiveSource:
    def __init__(self, spec: dict[str, Any]):
        self.search = spec.get("search", "")
        self.name = f"remotive:{self.search or 'all'}"

    def fetch(self) -> list[JobPosting]:
        url = "https://remotive.com/api/remote-jobs"
        if self.search:
            url += f"?search={quote(self.search)}"
        data = http_json(url)
        jobs = []
        for j in data.get("jobs", []):
            jobs.append(JobPosting(
                title=(j.get("title") or "").strip(),
                company=j.get("company_name", "") or "",
                location=j.get("candidate_required_location", "") or "Remote",
                url=j.get("url", "") or "",
                source=self.name,
                description=strip_html(j.get("description", "") or ""),
                salary_text=j.get("salary", "") or "",
                posted_at=j.get("publication_date", "") or "",
                remote=True,
            ))
        return jobs

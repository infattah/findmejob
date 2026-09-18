"""Greenhouse public job board API: https://boards-api.greenhouse.io/v1/boards/{board}/jobs"""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_json, strip_html


class GreenhouseSource:
    def __init__(self, spec: dict[str, Any]):
        self.board = spec["board"]
        self.name = f"greenhouse:{self.board}"

    def fetch(self) -> list[JobPosting]:
        data = http_json(
            f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        )
        jobs = []
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            jobs.append(JobPosting(
                title=j.get("title", "").strip(),
                company=self.board,
                location=loc,
                url=j.get("absolute_url", ""),
                source=self.name,
                description=strip_html(j.get("content", "") or ""),
                posted_at=j.get("updated_at", "") or "",
                remote="remote" in loc.lower(),
            ))
        return jobs

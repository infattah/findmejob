"""Ashby public posting API: https://api.ashbyhq.com/posting-api/job-board/{board}"""
from __future__ import annotations

from typing import Any
import time

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
                apply_url=(j.get("applyUrl") or "").strip(),
                source_liveness=("alive" if j.get("isListed") is True and j.get("applyUrl")
                                 else "expired" if j.get("isListed") is False else ""),
                source_liveness_checked_at=time.time(),
                source_liveness_detail=(
                    "Ashby posting API: isListed=true and applyUrl present"
                    if j.get("isListed") is True and j.get("applyUrl") else
                    "Ashby posting API: isListed=false" if j.get("isListed") is False else ""),
            ))
        return jobs

"""Lever public postings API: https://api.lever.co/v0/postings/{company}?mode=json"""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_json, strip_html


class LeverSource:
    def __init__(self, spec: dict[str, Any]):
        self.company = spec["company"]
        self.name = f"lever:{self.company}"

    def fetch(self) -> list[JobPosting]:
        data = http_json(f"https://api.lever.co/v0/postings/{self.company}?mode=json")
        jobs = []
        for j in data:
            cats = j.get("categories") or {}
            loc = cats.get("location", "") or ""
            desc_parts = [j.get("descriptionPlain", "") or ""]
            for lst in j.get("lists", []) or []:
                desc_parts.append(lst.get("text", ""))
                desc_parts.append(lst.get("content", ""))
            jobs.append(JobPosting(
                title=j.get("text", "").strip(),
                company=self.company,
                location=loc,
                url=j.get("hostedUrl", "") or "",
                source=self.name,
                description=strip_html(" ".join(desc_parts)),
                posted_at=str(j.get("createdAt", "")),
                remote="remote" in loc.lower(),
            ))
        return jobs

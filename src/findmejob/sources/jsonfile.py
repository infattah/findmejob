"""Local JSON source: saved searches, manual finds, the offline demo.

Format: a list of objects with title/company and optional location, url,
description, salary_text, posted_at, remote. See sample_data/sample_jobs.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import JobPosting


class JsonFileSource:
    def __init__(self, spec: dict[str, Any]):
        self.path = Path(spec["path"])
        self.name = spec.get("name") or f"jsonfile:{self.path.name}"

    def fetch(self) -> list[JobPosting]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        jobs = []
        for j in data:
            jobs.append(JobPosting(
                title=j.get("title", ""), company=j.get("company", ""),
                location=j.get("location", ""), url=j.get("url", ""),
                source=self.name, description=j.get("description", ""),
                salary_text=j.get("salary_text", ""), posted_at=j.get("posted_at", ""),
                remote=bool(j.get("remote", False)),
            ))
        return jobs

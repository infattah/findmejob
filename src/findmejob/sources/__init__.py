"""Job source adapters. Each adapter turns one public source into JobPostings."""
from __future__ import annotations

from typing import Any

from ..models import JobPosting


class SourceError(Exception):
    pass


def build_source(spec: dict[str, Any]):
    stype = spec.get("type", "")
    if stype == "greenhouse":
        from .greenhouse import GreenhouseSource
        return GreenhouseSource(spec)
    if stype == "lever":
        from .lever import LeverSource
        return LeverSource(spec)
    if stype == "workable":
        from .workable import WorkableSource
        return WorkableSource(spec)
    if stype == "rss":
        from .rss import RssSource
        return RssSource(spec)
    if stype == "remotive":
        from .remotive import RemotiveSource
        return RemotiveSource(spec)
    if stype == "jsonfile":
        from .jsonfile import JsonFileSource
        return JsonFileSource(spec)
    raise SourceError(f"unknown source type: {stype}")


def fetch_all(specs: list[dict[str, Any]]) -> tuple[list[JobPosting], list[str]]:
    jobs: list[JobPosting] = []
    errors: list[str] = []
    for spec in specs:
        try:
            jobs.extend(build_source(spec).fetch())
        except Exception as exc:  # one bad source must not kill the run
            errors.append(f"{spec.get('type')}: {exc}")
    return jobs, errors

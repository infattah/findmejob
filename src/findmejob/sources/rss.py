"""Generic RSS/Atom job feed adapter."""
from __future__ import annotations

from typing import Any

from ..models import JobPosting
from .base import http_text, parse_xml, strip_html


class RssSource:
    def __init__(self, spec: dict[str, Any]):
        self.url = spec["url"]
        self.name = spec.get("name") or f"rss:{self.url}"

    def fetch(self) -> list[JobPosting]:
        root = parse_xml(http_text(self.url))
        jobs: list[JobPosting] = []
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items:
            def child(tag: str) -> str:
                el = item.find(tag)
                if el is None:
                    el = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
                return (el.text or "") if el is not None else ""
            title = child("title").strip()
            link = child("link")
            if not link:
                el = item.find("{http://www.w3.org/2005/Atom}link")
                link = el.get("href", "") if el is not None else ""
            desc = child("description") or child("summary") or child("content")
            if title:
                jobs.append(JobPosting(
                    title=title, company=child("author") or self.name,
                    url=link.strip(), source=self.name,
                    description=strip_html(desc), posted_at=child("pubDate") or child("updated"),
                ))
        return jobs

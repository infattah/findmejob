"""Shared HTTP + parsing helpers for adapters.

Adapters call http_json/http_text. When the pipeline configures an
HttpCache (findmejob.sources.configure_cache), every adapter request goes
through it: fresh TTL hits skip the network, stale entries revalidate with
ETag/Last-Modified, and a source that errors with a cached body degrades to
stale data instead of killing the run.
"""
from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Optional

from ..httpcache import USER_AGENT, HttpCache

_cache: Optional[HttpCache] = None


def configure_cache(cache: Optional[HttpCache]) -> None:
    """Set the process-wide cache used by adapters (None disables caching)."""
    global _cache
    _cache = cache


def current_cache() -> Optional[HttpCache]:
    return _cache


def http_json(url: str, timeout: int = 30) -> Any:
    if _cache is not None:
        return json.loads(_cache.fetch_text(url, timeout=timeout).text)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def http_text(url: str, timeout: int = 30) -> str:
    if _cache is not None:
        return _cache.fetch_text(url, timeout=timeout).text
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)

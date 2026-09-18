"""Shared HTTP + parsing helpers for adapters."""
from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

USER_AGENT = "findmejob/0.1 (+https://github.com/infattah/findmejob)"


def http_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def http_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text)

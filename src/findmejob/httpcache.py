"""On-disk HTTP cache with ETag / Last-Modified revalidation and TTL.

Stdlib only. Repeated search runs should only pay for sources that actually
changed: fresh entries are served from disk, stale entries are revalidated
with conditional requests, and a 304 means the old body is still good.

The opener is injectable so tests never touch the network.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

USER_AGENT = "findmejob/0.2 (+https://github.com/infattah/findmejob)"

# (status, headers, body) returned by an opener; headers keys are lowercased
Opener = Callable[[str, dict, int], tuple[int, dict, str]]


def default_opener(url: str, headers: dict, timeout: int) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, body
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, {}, ""
        raise


@dataclass
class CacheResult:
    text: str
    from_cache: bool
    changed: bool  # False when served fresh or revalidated with 304


class HttpCache:
    """TTL + conditional-request cache. One file pair per URL in cache_dir."""

    def __init__(self, cache_dir: Path | str, ttl_seconds: int = 3600,
                 opener: Optional[Opener] = None, now: Callable[[], float] = time.time):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.opener = opener or default_opener
        self.now = now

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.meta.json", self.cache_dir / f"{key}.body"

    def _read(self, url: str) -> tuple[dict, str] | None:
        meta_path, body_path = self._paths(url)
        if not meta_path.exists() or not body_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return meta, body_path.read_text(encoding="utf-8", errors="replace")
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, url: str, headers: dict, body: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path, body_path = self._paths(url)
        meta = {
            "url": url,
            "fetched_at": self.now(),
            "etag": headers.get("etag", ""),
            "last_modified": headers.get("last-modified", ""),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        body_path.write_text(body, encoding="utf-8")

    def fetch_text(self, url: str, timeout: int = 30) -> CacheResult:
        cached = self._read(url)
        if cached:
            meta, body = cached
            if self.now() - float(meta.get("fetched_at", 0)) < self.ttl_seconds:
                return CacheResult(body, from_cache=True, changed=False)
        headers: dict = {}
        if cached:
            meta, _ = cached
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        try:
            status, resp_headers, body = self.opener(url, headers, timeout)
        except Exception:
            if cached:  # network trouble: serve stale rather than fail the run
                return CacheResult(cached[1], from_cache=True, changed=False)
            raise
        if status == 304 and cached:
            meta, old_body = cached
            meta["fetched_at"] = self.now()
            self._paths(url)[0].write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return CacheResult(old_body, from_cache=True, changed=False)
        self._write(url, resp_headers, body)
        return CacheResult(body, from_cache=False, changed=True)

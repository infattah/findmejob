"""Playwright session management. Optional dependency: pip install -e .[browser]

Uses a persistent profile directory so logins you do yourself in the opened
browser window are kept for the next run.
"""
from __future__ import annotations

from pathlib import Path


def open_session(profile_dir: Path, headless: bool = False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser support needs Playwright: pip install -e .[browser] && playwright install chromium"
        ) from exc
    profile_dir.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        str(profile_dir), headless=headless,
        viewport={"width": 1280, "height": 900},
    )
    return pw, ctx

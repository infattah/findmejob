"""Master CV ingestion.

Primary format: structured markdown (see sample_data/master_cv.example.md).
Freeform text is accepted and stored as raw_text; use an LLM provider or a
coding agent to convert freeform CVs into the structured format.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .models import Education, Experience, Profile

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_LINK = re.compile(r"^(\w[\w ]*)\s*:\s*(\S+)$")


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        try:
            out = subprocess.run(
                ["pdftotext", str(path), "-"], capture_output=True, check=True, timeout=60
            )
            return out.stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "PDF parsing needs `pdftotext` (poppler-utils). "
                "Convert your CV to markdown instead - see sample_data/master_cv.example.md"
            ) from exc
    if suffix in (".docx",):
        raise RuntimeError(
            "DOCX is not parsed directly. Convert to markdown or PDF first."
        )
    return path.read_text(encoding="utf-8")


def parse_master_cv(text: str) -> Profile:
    profile = Profile(raw_text=text)
    section = ""
    current_exp: Experience | None = None
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            low = title.lower()
            if level == 1 and not profile.full_name:
                profile.full_name = title
                continue
            if level == 2:
                section = low
                current_exp = None
                continue
            if level == 3 and section.startswith("experience"):
                role, company, start, end = _parse_exp_heading(title)
                current_exp = Experience(role=role, company=company, start=start, end=end)
                profile.experiences.append(current_exp)
                continue
            if level == 3 and section.startswith("education"):
                degree, _, school = title.partition(" - ")
                profile.education.append(Education(degree=degree.strip(), school=school.strip()))
                continue
        stripped = line.strip()
        if not stripped:
            continue
        if i < 6 and not profile.email and ("@" in stripped or "|" in stripped):
            _parse_contact_line(profile, stripped)
            continue
        if section.startswith("summary"):
            profile.summary = (profile.summary + " " + stripped).strip()
        elif section.startswith("skills") and stripped.startswith("- "):
            profile.skills.append(stripped[2:].strip())
        elif section.startswith("links"):
            lm = _LINK.match(stripped.lstrip("- "))
            if lm:
                profile.links[lm.group(1).strip().lower()] = lm.group(2).strip()
        elif section.startswith("experience") and current_exp and stripped.startswith("- "):
            current_exp.bullets.append(stripped[2:].strip())

    if not profile.headline and profile.experiences:
        profile.headline = profile.experiences[0].role
    return profile


def _parse_exp_heading(title: str) -> tuple[str, str, str, str]:
    # "Role - Company (2020 - Present)"
    dates = ""
    m = re.search(r"\(([^)]*)\)\s*$", title)
    if m:
        dates = m.group(1)
        title = title[: m.start()].strip()
    role, _, company = title.partition(" - ")
    start, _, end = dates.partition(" - ")
    return role.strip(), company.strip(), start.strip(), end.strip()


def _parse_contact_line(profile: Profile, line: str) -> None:
    for part in re.split(r"\s*\|\s*", line):
        part = part.strip()
        if "@" in part and not profile.email:
            profile.email = part
        elif re.search(r"(\+|\d{6,})", part) and not profile.phone:
            profile.phone = part
        elif part.startswith("http"):
            host = re.sub(r"https?://(www\.)?", "", part).split("/")[0]
            profile.links.setdefault(host, part)

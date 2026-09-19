"""Minimal, dependency-free PDF writer for tailored CVs.

Produces a clean, ATS-safe, single-column document using the built-in
Helvetica fonts every PDF viewer ships. Markdown stays the source of
truth; this renders the same structured profile into a designed PDF.

Deliberate constraints:
- single column, standard fonts, real text (not images): ATS parsers read it
- WinAnsi text; characters outside latin-1 degrade to '?' rather than
  breaking the file
- no external dependencies, so the core install stays zero-dependency
"""
from __future__ import annotations

from pathlib import Path

PAGE_W, PAGE_H = 595.0, 842.0  # A4 in points
MARGIN = 54.0
BOTTOM = 60.0

# approximate Helvetica advance widths as a fraction of font size,
# bucketed by character class (good enough for left-aligned wrapping)
_NARROW = set("iljtfI.,:;'!|()[] ")
_WIDE = set("mwMW@%")
_MID_WIDE = set("ABCDEFGHKNOPQRSTUVXYZ&")


def _char_w(ch: str) -> float:
    if ch in _NARROW:
        return 0.28
    if ch in _WIDE:
        return 0.85
    if ch in _MID_WIDE:
        return 0.66
    if ch.isdigit():
        return 0.55
    return 0.50


def _width(text: str, size: float) -> float:
    return sum(_char_w(c) for c in text) * size


def _wrap(text: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        if _width(cur + " " + w, size) <= max_w:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _esc(text: str) -> str:
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class _Layout:
    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.y = PAGE_H - MARGIN

    @property
    def ops(self) -> list[str]:
        return self.pages[-1]

    def _need(self, height: float) -> None:
        if self.y - height < BOTTOM:
            self.pages.append([])
            self.y = PAGE_H - MARGIN

    def text(self, text: str, size: float = 10.5, font: str = "F1",
             indent: float = 0.0, after: float = 4.0, leading: float | None = None,
             wrap_width: float | None = None) -> None:
        leading = leading or size * 1.35
        max_w = (wrap_width or PAGE_W) - MARGIN * 2 - indent
        for line in _wrap(text, size, max_w):
            self._need(leading + after)
            self.ops.append(f"BT /{font} {size} Tf {MARGIN + indent:.1f} {self.y:.1f} Td ({_esc(line)}) Tj ET")
            self.y -= leading
        self.y -= after

    def rule(self, after: float = 8.0) -> None:
        self._need(6 + after)
        y = self.y + 2
        self.ops.append(f"0.75 w {MARGIN:.1f} {y:.1f} m {PAGE_W - MARGIN:.1f} {y:.1f} l S")
        self.y -= after

    def heading(self, text: str, after: float = 14.5) -> None:
        # Baseline math: heading glyphs sit on y; the rule goes 7pt below
        # that baseline; the next block starts ~14pt under the rule so its
        # ascenders clear it.
        self._need(21 + after)
        y = self.y
        self.ops.append(f"BT /F2 12.5 Tf {MARGIN:.1f} {y:.1f} Td ({_esc(text)}) Tj ET")
        rule_y = y - 7.0
        self.ops.append(f"0.75 w {MARGIN:.1f} {rule_y:.1f} m {PAGE_W - MARGIN:.1f} {rule_y:.1f} l S")
        self.y = rule_y - after

    def bullet(self, text: str, size: float = 10.5, after: float = 2.5) -> None:
        leading = size * 1.32
        max_w = PAGE_W - MARGIN * 2 - 14
        lines = _wrap(text, size, max_w)
        for i, line in enumerate(lines):
            self._need(leading + after)
            prefix = chr(0x95) + "  " if i == 0 else "    "  # WinAnsi bullet
            self.ops.append(
                f"BT /F1 {size} Tf {MARGIN:.1f} {self.y:.1f} Td ({_esc(prefix + line)}) Tj ET")
            self.y -= leading
        self.y -= after

    def spacer(self, pts: float) -> None:
        self.y -= pts


def _build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode("latin-1") if isinstance(body, str) else body)
        return len(objects)  # 1-based object number

    catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add(b"")  # placeholder, filled after kids are known
    font1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids: list[int] = []
    for ops in pages:
        stream = ("\n".join(ops) + "\n").encode("latin-1", errors="replace")
        content_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream")
        page_id = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
            f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
            f"/Contents {content_id} 0 R >>")
        kids.append(page_id)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode("latin-1")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


def render_profile_pdf(lines_plan, out_path: Path | str) -> Path:
    """Render a layout plan (list of (kind, text) tuples) to PDF.

    kinds: name, contact, heading, body, bullet, spacer
    """
    lay = _Layout()
    for kind, text in lines_plan:
        if kind == "name":
            lay.text(text, 20, "F2", after=2.0)
        elif kind == "contact":
            lay.text(text, 9.5, "F1", after=2.0)
        elif kind == "heading":
            lay.spacer(4)
            lay.heading(text)
        elif kind == "subhead":
            lay.text(text, 11, "F2", after=1.5)
        elif kind == "body":
            lay.text(text, 10.5, "F1", after=3.5)
        elif kind == "bullet":
            lay.bullet(text)
        elif kind == "spacer":
            lay.spacer(6)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_build_pdf(lay.pages))
    return path


def render_cv_pdf(profile, job, out_path: Path | str) -> Path:
    """Designed PDF of the tailored CV: same content as render_cv_markdown,
    same ordering rules (tailor.rank_skills / rank_bullets)."""
    from ..tailor import rank_bullets, rank_skills

    plan: list[tuple[str, str]] = [(("name"), profile.full_name or "Curriculum Vitae")]
    contact = "  |  ".join(p for p in [profile.email, profile.phone] if p)
    if contact:
        plan.append(("contact", contact))
    if profile.links:
        plan.append(("contact", "  |  ".join(f"{k}: {v}" for k, v in profile.links.items())))
    if profile.headline:
        plan.append(("body", profile.headline))
    if profile.summary:
        plan.append(("heading", "Summary"))
        plan.append(("body", profile.summary))
    skills = rank_skills(profile, job)
    if skills:
        plan.append(("heading", "Skills"))
        plan.append(("body", ("  " + chr(0x95) + "  ").join(skills)))
    if profile.experiences:
        plan.append(("heading", "Experience"))
        for exp in profile.experiences:
            dates = " - ".join(p for p in [exp.start, exp.end] if p)
            head = f"{exp.role} - {exp.company}" + (f"   ({dates})" if dates else "")
            plan.append(("subhead", head))
            for b in rank_bullets(exp.bullets, job):
                plan.append(("bullet", b))
            plan.append(("spacer", ""))
    if profile.education:
        plan.append(("heading", "Education"))
        for edu in profile.education:
            line = f"{edu.degree} - {edu.school}" + (f"   ({edu.year})" if edu.year else "")
            plan.append(("subhead", line))
    return render_profile_pdf(plan, out_path)

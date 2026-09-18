"""Application email drafts and optional SMTP sending.

Default behavior is draft-only: emails are written to output/emails/ for
review. Sending requires SMTP settings in .env AND an explicit send call.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .models import JobPosting, Profile
from .tailor import draft_email


def compose(profile: Profile, job: JobPosting, cfg: Config) -> tuple[str, str]:
    return draft_email(profile, job)


def save_draft(out_dir: Path, profile: Profile, job: JobPosting, cfg: Config,
               attachment: Path | None = None) -> Path:
    subject, body = compose(profile, job, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{job.id}_email.txt"
    lines = [f"To: <fill in recipient>", f"Subject: {subject}", ""]
    if attachment:
        lines.append(f"Attachment: {attachment}")
        lines.append("")
    lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def send(to: str, subject: str, body: str, attachment: Path | None = None) -> None:
    host = os.environ.get("FINDMEJOB_SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP not configured. Set FINDMEJOB_SMTP_* in .env.")
    msg = EmailMessage()
    msg["From"] = os.environ.get("FINDMEJOB_SMTP_USER", "")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=attachment.name)
    port = int(os.environ.get("FINDMEJOB_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ.get("FINDMEJOB_SMTP_USER", ""),
                   os.environ.get("FINDMEJOB_SMTP_PASSWORD", ""))
        smtp.send_message(msg)

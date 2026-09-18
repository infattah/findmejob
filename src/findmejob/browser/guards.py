"""Safety guards for browser automation.

Pure functions over page text/HTML. The apply flow calls these before and
during form filling. Any hit raises PausedForHuman and the run stops with a
clear reason recorded in the tracker. We never try to defeat a guard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CAPTCHA_PATTERNS = [
    r"captcha", r"recaptcha", r"hcaptcha", r"cloudflare", r"are you a robot",
    r"verify you are human", r"i'm not a robot", r"turnstile",
]
PAYMENT_PATTERNS = [
    r"payment", r"credit card", r"card number", r"checkout", r"subscribe to apply",
    r"premium (plan|account|membership)", r"pay to apply", r"billing",
]
ACCOUNT_PATTERNS = [
    r"create (an )?account", r"sign up to (apply|continue)", r"register to apply",
    r"log ?in to (apply|continue)",
]
UNKNOWN_FIELD_HINTS = [
    r"cover letter\s*\*", r"portfolio\s*\*", r"salary (expectation|requirement)",
    r"notice period", r"visa", r"sponsorship", r"right to work", r"relocation",
]


@dataclass
class StopReason:
    kind: str  # captcha | payment | account_required | unknown_field | submit_gate
    detail: str


class PausedForHuman(Exception):
    def __init__(self, reason: StopReason):
        super().__init__(f"{reason.kind}: {reason.detail}")
        self.reason = reason


def _scan(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def check_page(text: str, never_pay: bool = True, never_create_accounts: bool = True) -> None:
    hit = _scan(CAPTCHA_PATTERNS, text)
    if hit:
        raise PausedForHuman(StopReason("captcha", f"page shows a human check ({hit}); solve it yourself, then resume"))
    if never_pay:
        hit = _scan(PAYMENT_PATTERNS, text)
        if hit:
            raise PausedForHuman(StopReason("payment", f"page asks for payment ({hit}); findmejob never pays to apply"))
    if never_create_accounts:
        hit = _scan(ACCOUNT_PATTERNS, text)
        if hit:
            raise PausedForHuman(StopReason("account_required", f"site requires an account ({hit}); ask the user whether to create one"))


def check_required_field(label: str, known_answers: dict[str, str]) -> None:
    """Raise if a required field has no known answer in the profile/config."""
    label_low = label.lower().strip()
    if not label_low:
        return
    if _scan(UNKNOWN_FIELD_HINTS, label_low) and label_low not in {k.lower() for k in known_answers}:
        raise PausedForHuman(StopReason(
            "unknown_field",
            f"form asks '{label}' which the profile cannot answer; ask the user, do not guess"))

"""Salary parsing and normalization.

Design rules (learned from aggregator libraries that guess wrong):
- Preserve the raw text. Normalized values are derived, never a replacement.
- Never invent a currency. "$" alone is ambiguous (USD, SGD, AUD, HKD...);
  only an explicit code or unambiguous symbol sets the currency.
- Never invent an exchange rate. Conversion needs a rate the user supplied
  in config (salary.rates: units of base currency per 1 unit of source).
- Ambiguity is represented, not resolved silently: every Salary carries
  notes explaining what was assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Unambiguous symbols only. "$" is deliberately absent.
_SYMBOLS = {"€": "EUR", "£": "GBP", "₹": "INR", "د.إ": "AED", "﷼": "SAR"}
_KNOWN_CODES = {
    "USD", "EUR", "GBP", "AED", "SAR", "QAR", "OMR", "KWD", "BHD", "INR",
    "SGD", "AUD", "CAD", "JPY", "CHF", "PKR", "EGP", "ZAR", "MYR", "PHP",
    "US$",
}

_PERIODS = {
    "year": ["per year", "a year", "yearly", "annually", "per annum", "p.a.", "/yr", "/year", " pa"],
    "month": ["per month", "a month", "monthly", "/mo", "/month", "p.m.", " pm"],
    "week": ["per week", "weekly", "/wk", "/week"],
    "day": ["per day", "daily", "/day"],
    "hour": ["per hour", "hourly", "/hr", "/hour", "an hour"],
}

_HOURS_PER_YEAR = 2080
_DAYS_PER_YEAR = 260
_WEEKS_PER_YEAR = 52

_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?")


@dataclass
class Salary:
    raw: str
    min: Optional[float] = None
    max: Optional[float] = None
    currency: str = ""   # ISO code, or "" when unknown/ambiguous
    period: str = ""     # year|month|week|day|hour, or "" when unstated
    notes: list[str] = field(default_factory=list)

    def annual_min(self) -> Optional[float]:
        return to_annual(self.min, self.period) if self.min is not None else None

    def annual_max(self) -> Optional[float]:
        return to_annual(self.max, self.period) if self.max is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {"raw": self.raw, "min": self.min, "max": self.max,
                "currency": self.currency, "period": self.period, "notes": self.notes}


def to_annual(amount: float, period: str) -> float:
    return amount * {
        "year": 1, "month": 12, "week": _WEEKS_PER_YEAR,
        "day": _DAYS_PER_YEAR, "hour": _HOURS_PER_YEAR,
    }.get(period, 1)


def _detect_currency(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    upper = text.upper()
    if "US$" in upper:
        return "USD", notes
    for code in sorted(_KNOWN_CODES - {"US$"}, key=len, reverse=True):
        if re.search(rf"(?<![A-Z]){re.escape(code)}(?![A-Z])", upper):
            return code, notes
    for sym, code in _SYMBOLS.items():
        if sym in text:
            return code, notes
    if "$" in text:
        notes.append("'$' is ambiguous; currency left unset")
    return "", notes


def _detect_period(text: str) -> tuple[str, list[str]]:
    low = " " + text.lower() + " "
    for period, markers in _PERIODS.items():
        if any(m in low for m in markers):
            return period, []
    return "", ["pay period not stated; annual comparison skipped"]


def parse_salary(text: str) -> Optional[Salary]:
    """Parse free-text compensation into a Salary, or None if nothing numeric."""
    if not text or not text.strip():
        return None
    raw = text.strip()
    notes: list[str] = []
    values: list[float] = []
    for m in _NUM.finditer(raw):
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000
        values.append(val)
    # ignore small stray numbers that are clearly not money (e.g. "5 days")
    money = [v for v in values if v >= 10]
    if not money:
        return None
    currency, cur_notes = _detect_currency(raw)
    period, per_notes = _detect_period(raw)
    notes.extend(cur_notes)
    notes.extend(per_notes)
    lo, hi = min(money), max(money)
    if not period:
        # heuristic used only to label, never to convert
        if hi >= 40000:
            notes.append("magnitude suggests an annual figure")
        elif hi <= 500:
            notes.append("magnitude suggests an hourly/daily figure")
    return Salary(raw=raw, min=lo, max=hi, currency=currency, period=period, notes=notes)


@dataclass
class NormalizedSalary:
    salary: Salary
    base_currency: str
    annual_min: Optional[float] = None
    annual_max: Optional[float] = None
    converted: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"salary": self.salary.to_dict(), "base_currency": self.base_currency,
                "annual_min": self.annual_min, "annual_max": self.annual_max,
                "converted": self.converted, "notes": self.notes}


def normalize(salary: Salary, base_currency: str, rates: dict[str, float]) -> NormalizedSalary:
    """Annual figures in base_currency, using only user-supplied rates.

    rates maps a currency code to the value of 1 unit in the base currency,
    e.g. with base USD: {"AED": 0.272, "EUR": 1.08}.
    """
    base = (base_currency or "").upper()
    notes = list(salary.notes)
    out = NormalizedSalary(salary=salary, base_currency=base)
    if not salary.period:
        notes.append("cannot annualize: pay period unknown")
        out.notes = notes
        return out
    if not salary.currency:
        notes.append(f"cannot convert to {base or 'base currency'}: currency unknown")
        out.notes = notes
        return out
    if salary.currency == base:
        rate = 1.0
    else:
        rate = rates.get(salary.currency)
        if rate is None:
            notes.append(
                f"no configured rate for {salary.currency}->{base}; "
                "add it under salary.rates in config.json")
            out.notes = notes
            return out
    if salary.min is not None:
        out.annual_min = to_annual(salary.min, salary.period) * rate
    if salary.max is not None:
        out.annual_max = to_annual(salary.max, salary.period) * rate
    out.converted = True
    out.notes = notes
    return out


# ---------------------------------------------------------------- listing extraction

_PAY_WORDS = re.compile(
    r"\b(salary|salaries|compensation|remuneration|pay|pay range|package|ctc|wage|wages|"
    r"stipend|base pay|ote)\b", re.I)
_MONEY = re.compile(
    r"(?:(?<![A-Za-z])(?:US\$|[A-Z]{3})\s?\d|[€£₹$﷼]\s?\d|\d[\d,.]*\s?[kK]?\s?(?:[A-Z]{3})(?![A-Za-z])|د\.إ)")
_NOT_PAY = re.compile(r"\b(revenue|turnover|funding|raised|valuation|budget|billion|million|years?|yrs)\b", re.I)


def _period_marked(text: str) -> bool:
    low = " " + text.lower() + " "
    return any(m in low for markers in _PERIODS.values() for m in markers)


def extract_salary_text(description: str, max_len: int = 200) -> str:
    """Find the compensation statement inside a job description.

    Returns the matching sentence verbatim (trimmed), or "" when the listing
    does not state pay. A match needs a money amount plus either a pay word
    ("salary", "package", "compensation"...) or a pay period ("per month").
    Company revenue, budgets and "5 years" are not treated as pay.
    The raw text is what gets stored; parse_salary() derives numbers later."""
    if not description:
        return ""
    text = re.sub(r"<[^>]+>", " ", description)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])|[\r\n]+|\s[•·|]\s", text)
    best = ""
    best_rank = 99
    for part in parts:
        chunk = " ".join(part.split())
        if not chunk or not re.search(r"\d", chunk):
            continue
        has_money = bool(_MONEY.search(chunk))
        has_word = bool(_PAY_WORDS.search(chunk))
        has_period = _period_marked(chunk)
        if has_money and (has_word or has_period):
            rank = 0 if has_word else 1
        elif has_word and parse_salary(chunk) and (parse_salary(chunk).max or 0) >= 1000 \
                and not _NOT_PAY.search(chunk):
            rank = 2
        else:
            continue
        if has_money and _NOT_PAY.search(chunk) and not has_word:
            continue
        if rank < best_rank:
            best, best_rank = chunk, rank
    if len(best) > max_len:
        m = _MONEY.search(best) or re.search(r"\d", best)
        start = max(0, (m.start() if m else 0) - max_len // 3)
        best = best[start:start + max_len].strip()
    return best

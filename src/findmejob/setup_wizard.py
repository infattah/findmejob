"""Guided setup for people who do not want to hand-edit JSON.

`findmejob setup` asks plain questions and writes config.json.
`findmejob doctor` checks the setup and says what is missing.

The config builder is pure and separately testable; only run_wizard does I/O.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG_NAME, load_config, scaffold


def build_config_from_answers(a: dict[str, Any]) -> dict[str, Any]:
    """Turn plain-language answers into a config dict.

    answers: full_name, email, phone, roles (list), locations (list),
    salary_floor (int, 0 = none), currency, exclusions (list),
    remote_ok (bool), boards (list of {type, board|company|url...})
    """
    roles = [r.strip() for r in a.get("roles", []) if r.strip()]
    locations = [l.strip() for l in a.get("locations", []) if l.strip()]
    currency = (a.get("currency") or "USD").upper()
    sources: list[dict[str, Any]] = []
    if roles:
        sources.append({"type": "remotive", "search": roles[0]})
    for board in a.get("boards", []) or []:
        if board.get("type") and board.get("type") != "remotive":
            sources.append(board)
    return {
        "profile": {
            "master_cv": "data/profile/master_cv.md",
            "full_name": a.get("full_name", ""),
            "email": a.get("email", ""),
            "phone": a.get("phone", ""),
            "links": a.get("links", {}),
        },
        "search": {
            "role_keywords": roles,
            "cache_ttl_seconds": 3600,
            "sources": sources,
        },
        "policy": {
            "salary_floor": int(a.get("salary_floor") or 0),
            "currency": currency,
            "exchange_rates": a.get("exchange_rates", {}),
            "locations_include": locations + (["Remote"] if a.get("remote_ok", True) else []),
            "locations_exclude": [],
            "sector_exclusions": [x.strip() for x in a.get("exclusions", []) if x.strip()],
            "title_exclude": ["intern", "unpaid"],
            "min_fit_score": 45,
        },
        "autonomy": {
            "auto_apply": False,
            "require_confirmation": True,
            "max_applications_per_run": 5,
            "never_pay": True,
            "never_create_accounts": True,
        },
        "llm": {"provider": "none", "model": "", "api_key_env": "ANTHROPIC_API_KEY"},
        "email": {"from_name": a.get("full_name", ""), "signature": ""},
        "paths": {
            "db": "data/findmejob.db",
            "output": "output",
            "browser_profile": "data/browser-profile",
            "cache": "data/http-cache",
        },
    }


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        ans = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    return ans or default



def _ask_nonnegative_int(prompt: str, default: int = 0) -> int:
    """Ask until a whole, non-negative number is entered."""
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw.replace(",", "").strip())
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            print("  Enter a whole number of 0 or more, for example 60000.")


def run_wizard(root: Path) -> Path:
    print("findmejob setup - answer a few questions; you can edit config.json later.")
    scaffold(root)
    full_name = _ask("Your full name")
    email = _ask("Email for applications")
    phone = _ask("Phone (optional)")
    roles = _ask("Target roles, comma separated (e.g. marketing manager, growth lead)")
    locations = _ask("Locations you accept, comma separated (e.g. Dubai, London)")
    remote = _ask("Include remote roles? (y/n)", "y").lower().startswith("y")
    salary = _ask_nonnegative_int("Minimum yearly salary in your currency (0 = no floor)")
    currency = _ask("Your salary currency (e.g. USD, EUR, AED)", "USD")
    exclusions = _ask("Anything to exclude, comma separated (sectors, words; optional)")
    boards_raw = _ask("Companies' career boards to watch, comma separated\n"
                      "  (format ats:name, ats in greenhouse/lever/ashby/smartrecruiters/workable; optional)")
    boards: list[dict[str, Any]] = []
    for item in [b.strip() for b in boards_raw.split(",") if b.strip()]:
        ats, _, name = item.partition(":")
        key = {"greenhouse": "board", "ashby": "board", "lever": "company",
               "smartrecruiters": "company", "workable": "subdomain"}.get(ats.lower())
        if key and name:
            boards.append({"type": ats.lower(), key: name})
        else:
            print(f"  skipped '{item}' - expected ats:name")
    answers = {
        "full_name": full_name, "email": email, "phone": phone,
        "roles": [r.strip() for r in roles.split(",")],
        "locations": [l.strip() for l in locations.split(",")],
        "remote_ok": remote, "salary_floor": salary,
        "currency": currency, "exclusions": [x.strip() for x in exclusions.split(",")],
        "boards": boards,
    }
    cfg = build_config_from_answers(answers)
    path = root / DEFAULT_CONFIG_NAME
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {path}")
    print("Next: findmejob ingest --cv your_master_cv.md, then findmejob doctor")
    return path


def doctor(root: Path) -> list[tuple[str, str]]:
    """Return (level, message) checks: level is ok | warn | fail."""
    checks: list[tuple[str, str]] = []
    cfg_path = root / DEFAULT_CONFIG_NAME
    if not cfg_path.exists():
        return [("fail", f"no {DEFAULT_CONFIG_NAME} - run: findmejob setup")]
    try:
        cfg = load_config(root)
        checks.append(("ok", "config.json parses"))
    except Exception as exc:
        return [("fail", f"config.json is invalid: {exc}")]

    cv_rel = cfg.profile.get("master_cv", "")
    cv_path = cfg.resolve(cv_rel) if cv_rel else None
    if not cv_path or not cv_path.exists():
        checks.append(("fail", "no master CV - run: findmejob ingest --cv your_cv.md"))
    else:
        from .profile import extract_text, parse_master_cv
        profile = parse_master_cv(extract_text(cv_path))
        if profile.experiences:
            checks.append(("ok", f"master CV found: {len(profile.experiences)} roles, "
                                 f"{len(profile.skills)} skills"))
        else:
            checks.append(("warn", "master CV has no structured experience sections "
                                   "(see sample_data/master_cv.example.md)"))
        if not (profile.full_name or cfg.profile.get("full_name")):
            checks.append(("warn", "no name on the CV or in config"))

    sources = cfg.search.get("sources", [])
    if not sources:
        checks.append(("warn", "no job sources configured - add some under search.sources "
                               "or rerun findmejob setup"))
    else:
        from .sources import SourceError, build_source
        for spec in sources:
            try:
                src = build_source(spec)
                checks.append(("ok", f"source '{src.name}' is configured"))
            except (SourceError, KeyError) as exc:
                checks.append(("fail", f"source {spec.get('type')}: {exc}"))

    if not cfg.profile.get("email"):
        checks.append(("warn", "no email in profile - application drafts will lack contact info"))
    for rel, label in [(cfg.paths["db"], "database"), (cfg.paths["output"], "output folder")]:
        parent = cfg.resolve(rel).parent if label == "database" else cfg.resolve(rel)
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks.append(("ok", f"{label} path is writable"))
        except OSError as exc:
            checks.append(("fail", f"{label} path is not writable: {exc}"))
    floor = int(cfg.policy.get("salary_floor") or 0)
    if floor and not cfg.policy.get("exchange_rates"):
        checks.append(("warn", "salary floor set without exchange_rates - salaries in "
                               "other currencies require review until rates are configured"))
    return checks

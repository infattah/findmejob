"""findmejob CLI - one of two clients of the persistent main agent."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .agent.main_agent import MainAgent
from .config import load_config, scaffold
from .pipeline import load_profile, run_search, run_tailor, run_triage
from .profile import extract_text, parse_master_cv
from .tracker import Tracker


def _agent(args) -> tuple[MainAgent, Tracker]:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    return MainAgent(cfg, tracker), tracker


def cmd_init(args) -> int:
    root = Path(args.dir) if args.dir else Path.cwd()
    created = scaffold(root)
    print("Created:" if created else "Already set up.")
    for c in created:
        print(" ", c)
    print("\nNext: edit config.json, then: findmejob ingest --cv your_master_cv.md")
    return 0


def cmd_ingest(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    src = Path(args.cv)
    if not src.exists():
        print(f"no such file: {src}", file=sys.stderr)
        return 1
    dest = cfg.resolve("data/profile/master_cv" + (".md" if src.suffix.lower() in (".md", ".txt") else src.suffix.lower()))
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = extract_text(src)
    dest.write_text(text, encoding="utf-8")
    # Keep the scaffolded config in sync so the very next command can load the CV.
    import json
    cfg_path = cfg.root / "config.json"
    raw = dict(cfg.raw)
    profile_cfg = dict(raw.get("profile", {}))
    profile_cfg["master_cv"] = str(dest.relative_to(cfg.root)) if dest.is_relative_to(cfg.root) else str(dest)
    raw["profile"] = profile_cfg
    cfg_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    cfg.raw = raw
    profile = parse_master_cv(text)
    print(f"Ingested {profile.full_name or 'master CV'}: {len(profile.skills)} skills, "
          f"{len(profile.experiences)} roles, {len(profile.links)} links")
    print(f"Stored at {dest}")
    if not profile.experiences:
        print("Note: no structured experience found. Use the markdown format in "
              "sample_data/master_cv.example.md, or ask your coding agent to convert it.")
    return 0


def cmd_search(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    res = run_search(cfg, tracker)
    print(f"Fetched {res['fetched']} roles, {res['new']} new.")
    for e in res["errors"]:
        print(f"  source error: {e}")
    if not args.no_triage:
        try:
            tri = run_triage(cfg, tracker)
            print(f"Shortlisted {tri['shortlisted']}, {tri['needs_review']} need your review, "
                  f"{tri['below_floor']} below the bar.")
        except FileNotFoundError as exc:
            print(exc)
    return 0


def cmd_triage(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    try:
        tri = run_triage(cfg, tracker)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Shortlisted {tri['shortlisted']}, {tri['needs_review']} need your review, "
          f"{tri['below_floor']} below the bar.")
    return 0


def cmd_tailor(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    res = run_tailor(cfg, tracker, args.job)
    if res.get("error"):
        print(res["error"], file=sys.stderr)
        return 1
    print(f"CV:    {res['cv']}")
    print(f"Email: {res['email']}")
    if res["fidelity_warnings"]:
        print("Fidelity check flagged terms not in your master CV:")
        for w in res["fidelity_warnings"]:
            print(f"  - {w}")
    return 0


def cmd_apply(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    from .browser.apply_flow import apply_to_job
    job_id = tracker.resolve_job_id(args.job)
    if not job_id:
        print(f"no job matching '{args.job}'", file=sys.stderr)
        return 1
    job = tracker.get_job(job_id)
    profile = load_profile(cfg)
    res = apply_to_job(job, profile, cfg, tracker, submit=args.submit, headless=args.headless)
    print(f"status: {res['status']}")
    if res.get("stop"):
        print(f"stopped at: {res['stop']} - recorded in pending questions")
    if res.get("screenshot"):
        print(f"screenshot: {res['screenshot']}")
    return 0


def cmd_pack(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    from .packs import build_pack
    res = build_pack(cfg, tracker, args.job)
    if res.get("error"):
        print(res["error"], file=sys.stderr)
        return 1
    print(f"Pack: {res['pack_dir']}")
    for f in res["files"]:
        print(f"  {f}")
    if res["fidelity_warnings"]:
        print("Fidelity check flagged terms not in your master CV:")
        for w in res["fidelity_warnings"]:
            print(f"  - {w}")
    return 0


def cmd_refresh(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    if not args.verify:
        print("Nothing to do. Use --verify to check whether tracked listings are still live.")
        return 0
    from .liveness import check_listing
    active = {"new", "shortlisted", "tailored", "ready", "needs_input"}
    checked = expired = alive = unknown = 0
    for row in tracker.list_jobs():
        if row["status"] not in active or not row["url"]:
            continue
        if args.limit and checked >= args.limit:
            break
        checked += 1
        status, detail = check_listing(row["url"])
        if status == "expired":
            tracker.set_status(row["id"], "skipped", f"listing expired: {detail}")
            expired += 1
        elif status == "alive":
            tracker.add_event(row["id"], "liveness", f"alive: {detail}")
            alive += 1
        else:
            tracker.add_event(row["id"], "liveness", f"unknown: {detail}")
            unknown += 1
    print(f"Checked {checked}: {alive} alive, {expired} expired, {unknown} unknown.")
    return 0


def cmd_setup(args) -> int:
    from .setup_wizard import run_wizard
    run_wizard(Path(args.dir) if args.dir else Path.cwd())
    return 0


def cmd_doctor(args) -> int:
    from .setup_wizard import doctor
    checks = doctor(Path(args.dir) if args.dir else Path.cwd())
    icon = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
    failed = False
    for level, msg in checks:
        print(f"[{icon[level]}] {msg}")
        failed = failed or level == "fail"
    return 1 if failed else 0


def cmd_status(args) -> int:
    _, tracker = _agent(args)
    counts = tracker.counts()
    if not counts:
        print("Tracker is empty.")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    pend = tracker.pending()
    if pend:
        print(f"\nPending questions ({len(pend)}):")
        for i, r in enumerate(pend, 1):
            print(f"  {i}. {r['question']}")
    return 0


def cmd_list(args) -> int:
    _, tracker = _agent(args)
    rows = tracker.list_jobs(status=args.status)
    if not rows:
        print("No jobs.")
        return 0
    for r in rows:
        print(f"[{r['id']}] {r['title']} @ {r['company']} - {r['status']}"
              + (f" (score {r['score']})" if r["score"] is not None else ""))
        if r["url"]:
            print(f"    {r['url']}")
    return 0


def cmd_pending(args) -> int:
    _, tracker = _agent(args)
    rows = tracker.pending()
    if not rows:
        print("Nothing pending.")
        return 0
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['question']}")
    return 0


def cmd_answer(args) -> int:
    _, tracker = _agent(args)
    rows = tracker.pending()
    if not rows:
        print("Nothing pending.")
        return 0
    tracker.answer_pending(rows[0]["id"], " ".join(args.answer))
    print("Recorded.")
    return 0


def cmd_chat(args) -> int:
    agent, _ = _agent(args)
    if args.message:
        print(agent.handle(" ".join(args.message)))
        return 0
    print("findmejob chat. Type 'help' or Ctrl+C to exit.")
    while True:
        try:
            msg = input("you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        print("agent>", agent.handle(msg))
    return 0


def cmd_tick(args) -> int:
    agent, _ = _agent(args)
    summaries = agent.tick()
    print("\n".join(summaries) if summaries else "No queued tasks.")
    return 0


def cmd_runtimes(args) -> int:
    from .runtimes import detect_runtimes, select_runtime
    cfg = load_config(Path(args.dir) if args.dir else None)
    current = select_runtime(cfg.llm.get("provider", ""))
    print(f"Current runtime: {current.name}")
    for r in detect_runtimes():
        caps = ", ".join(k for k, v in r.capabilities.items() if v)
        print(f"  {r.name} [{r.kind}] available={'yes' if r.available else 'no'} ({caps})")
        print(f"      {r.setup_hint}")
    return 0


def cmd_ui(args) -> int:
    from .ui.server import serve
    cfg = load_config(Path(args.dir) if args.dir else None)
    serve(cfg, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="findmejob",
        description="Local-first AI job-search and application copilot.")
    parser.add_argument("--version", action="version", version=f"findmejob {__version__}")
    parser.add_argument("--dir", help="project directory (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create config and folders"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("ingest", help="ingest a master CV"); p.add_argument("--cv", required=True); p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("search", help="fetch roles from sources"); p.add_argument("--no-triage", action="store_true"); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("triage", help="policy check + fit scoring"); p.set_defaults(fn=cmd_triage)
    p = sub.add_parser("tailor", help="tailored CV + email draft"); p.add_argument("--job", required=True); p.set_defaults(fn=cmd_tailor)
    p = sub.add_parser("apply", help="browser-assisted apply"); p.add_argument("--job", required=True)
    p.add_argument("--submit", action="store_true", help="allow final submit (still gated by config)")
    p.add_argument("--headless", action="store_true"); p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("status", help="tracker overview"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("list", help="list jobs"); p.add_argument("--status"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("pending", help="list pending questions"); p.set_defaults(fn=cmd_pending)
    p = sub.add_parser("answer", help="answer the oldest pending question"); p.add_argument("answer", nargs="+"); p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("chat", help="talk to the main agent"); p.add_argument("message", nargs="*"); p.set_defaults(fn=cmd_chat)
    p = sub.add_parser("tick", help="run queued worker tasks"); p.set_defaults(fn=cmd_tick)
    p = sub.add_parser("runtimes", help="list agent runtimes and capabilities"); p.set_defaults(fn=cmd_runtimes)
    p = sub.add_parser("pack", help="build a full application pack for a role")
    p.add_argument("--job", required=True); p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("refresh", help="re-check tracked listings")
    p.add_argument("--verify", action="store_true", help="check listings are still live")
    p.add_argument("--limit", type=int, default=50); p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("setup", help="guided setup - answers become config.json"); p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("doctor", help="check your setup and say what is missing"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("ui", help="local web UI with chat"); p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787); p.set_defaults(fn=cmd_ui)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

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


def cmd_cv(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    try:
        profile = load_profile(cfg)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    job = None
    if args.job:
        tracker = Tracker(cfg.db_path)
        job_id = tracker.resolve_job_id(args.job)
        if not job_id:
            print(f"no job matching '{args.job}'", file=sys.stderr)
            return 1
        blocked = tracker.require_strong(job_id)
        if blocked:
            print(blocked, file=sys.stderr)
            return 1
        job = tracker.get_job(job_id)
    elif args.ad:
        try:
            text = sys.stdin.read() if args.ad == "-" else Path(args.ad).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read job ad: {exc}", file=sys.stderr)
            return 1
        if not text.strip():
            print("empty job ad", file=sys.stderr)
            return 1
        from .cvbuilder import job_from_ad
        job = job_from_ad(text, args.title, args.company)
    from .cvbuilder import build_cv
    photo = args.photo or cfg.profile.get("photo")
    out_dir = Path(args.out) if args.out else cfg.output_dir / "cvs"
    res = build_cv(profile, job, out_dir, style=args.style, photo=photo)
    print(f"CV:    {res['cv']}")
    print(f"PDF:   {res['pdf']}")
    for n in res["notes"]:
        print(f"note: {n}")
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
    from .liveness import check_job_liveness
    active = {"new", "shortlisted", "tailored", "ready", "needs_input"}
    checked = expired = alive = unknown = 0
    for row in tracker.list_jobs():
        if row["status"] not in active or not row["url"]:
            continue
        if args.limit and checked >= args.limit:
            break
        checked += 1
        status, detail = check_job_liveness(tracker.get_job(row["id"]))
        tracker.set_liveness(row["id"], status, detail)
        if status == "expired": expired += 1
        elif status == "alive": alive += 1
        else: unknown += 1
    from .pipeline import run_triage
    decisions = run_triage(cfg, tracker)
    print(f"Checked {checked}: {alive} alive, {expired} expired, {unknown} unknown. Decisions recomputed: {decisions}")
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


def _hunt_one(cfg, tracker, job_id: str, args) -> None:
    from .emailfinder import FinderInput, finder_from_config
    job = tracker.get_job(job_id)
    domain, confirmed = (args.domain or ""), bool(args.domain and args.confirmed)
    ver = tracker.get_verification(job_id)
    if not domain and ver and ver.official_domain:
        domain, confirmed = ver.official_domain, ver.status == "verified"
    pages = []
    if args.pages:
        import json
        pages = json.loads(Path(args.pages).read_text(encoding="utf-8"))
    finder_cfg = dict(cfg.raw.get("email_finder", {}))
    if args.no_search:
        finder_cfg["search_provider"] = "none"
    finder = finder_from_config(finder_cfg)
    listing = job.description + ("\n" + "\n".join(job.contact_emails) if job.contact_emails else "")
    hunt = finder.run(FinderInput(company=job.company, official_domain=domain,
                                  domain_confirmed=confirmed, listing_text=listing,
                                  listing_url=job.url, supplied_pages=pages))
    tracker.set_email_hunt(job_id, hunt)
    print(f"[{job_id}] {job.title} @ {job.company}: {hunt.summary()}")
    for m in hunt.methods:
        print(f"    {m.name:<14} {m.status:<8} {m.detail}")
    for e in hunt.emails:
        mark = "VERIFIED" if e.verified else "unverified"
        print(f"    {mark:<10} {e.address} ({e.role}, {e.method}) {e.source_url}"
              + (f" - {'; '.join(e.notes)}" if e.notes else ""))


def cmd_emails(args) -> int:
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    if args.outcome:
        job_id = tracker.resolve_job_id(args.job or "")
        if not job_id:
            print("--outcome needs --job", file=sys.stderr)
            return 1
        try:
            tracker.set_email_outcome(job_id, args.outcome, args.proof or "")
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"[{job_id}] email {args.outcome}")
        return 0
    if args.all:
        ids = tracker.jobs_needing_email_hunt()
        if not ids:
            print("Every qualified role already has a finished email hunt.")
    else:
        job_id = tracker.resolve_job_id(args.job or "")
        if not job_id:
            print(f"no job matching '{args.job}'", file=sys.stderr)
            return 1
        ids = [job_id]
    for job_id in ids:
        _hunt_one(cfg, tracker, job_id, args)
    counts = tracker.email_stage_counts()
    print("\nApplied roles by email route: " + ", ".join(f"{k.replace('applied_', '')} {v}" for k, v in counts.items()))
    return 0


def _print_agency(a, verbose: bool = False) -> None:
    site = f" https://{a.domain}/" if a.domain else ""
    print(f"[{a.id}] {a.name}{site} - {a.summary()}")
    if a.found_by:
        print(f"    found by: {', '.join(a.found_by)}")
    for c in a.checks:
        print(f"    {c.name:<14} {c.status:<8} {c.detail}")
    if verbose:
        for f in a.facts:
            print(f"    fact {f.field}: {f.value} <- {f.source_url} ({f.method})"
                  + (f" - {f.note}" if f.note else ""))


def cmd_agencies(args) -> int:
    from .agencies import DiscoveryRequest, build_from_config
    cfg = load_config(Path(args.dir) if args.dir else None)
    tracker = Tracker(cfg.db_path)
    if args.agency:
        agency_id = tracker.resolve_agency_id(args.agency)
        if not agency_id:
            print(f"no single agency matching '{args.agency}'", file=sys.stderr)
            return 1
        if args.outcome == "contacted":
            try:
                tracker.set_agency_contacted(agency_id, args.proof or "")
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"[{agency_id}] contacted")
            return 0
        _print_agency(tracker.get_agency(agency_id), verbose=True)
        return 0
    if args.list:
        rows = tracker.list_agencies(args.status, args.for_country or None)
        if not rows:
            print("No agencies tracked" + (f" with status {args.status}" if args.status else "") + ".")
        for a in rows:
            _print_agency(a, verbose=args.evidence)
        counts = tracker.agency_counts()
        print("\nAgencies by status: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    discovery, validator = build_from_config(cfg.raw, no_search=args.no_search)
    af = cfg.raw.get("agency_finder", {})
    if args.revalidate:
        targets = [a for a in tracker.list_agencies(args.status, args.for_country or None) if a.status != "contacted"]
        maps_ran = maps_key = bool(discovery.maps_api_key)
    else:
        supplied = None
        if args.pages:
            import json
            supplied = json.loads(Path(args.pages).read_text(encoding="utf-8"))
        methods = [m for m in (args.methods or ",".join(af.get("methods", []))).split(",") if m.strip()]
        skip = [m for m in (args.skip or "").split(",") if m.strip()]
        req = DiscoveryRequest(country=args.country, city=args.city or "", industry=args.industry or "",
                               country_code=args.country_code or "", limit=args.limit)
        try:
            run = discovery.run(req, methods=[m.strip() for m in methods] or None,
                                skip=[m.strip() for m in skip], jobs=tracker.all_jobs(), supplied=supplied)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Discovery for {', '.join(p for p in (args.city, args.country) if p)}"
              + (f" ({args.industry})" if args.industry else "") + ":")
        for m in run.methods:
            print(f"    {m.name:<14} {m.status:<8} {m.detail}")
        print(run.summary())
        for a in run.agencies:
            tracker.upsert_agency(a)
        targets = [] if args.no_validate else [tracker.get_agency(a.id) for a in run.agencies]
        ran = {m.name for m in run.methods if m.status in ("found", "empty")}
        maps_ran, maps_key = bool(ran & {"maps", "openstreetmap"}), "maps" in ran
    for a in targets:
        if a is None or a.status == "contacted":
            continue
        previous = a.id
        validator.validate(a, maps_ran=maps_ran, maps_key=maps_key)
        tracker.upsert_agency(a, previous_id=previous)
        _print_agency(a)
    counts = tracker.agency_counts()
    print("\nAgencies by status: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


def cmd_status(args) -> int:
    _, tracker = _agent(args)
    counts = tracker.counts()
    if not counts:
        print("Tracker is empty.")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    agencies = {k: v for k, v in tracker.agency_counts().items() if v}
    if agencies:
        print("  recruitment agencies: " + ", ".join(f"{k} {v}" for k, v in agencies.items()))
    if counts.get("applied"):
        print("  email route for applied roles:")
        for k, v in tracker.email_stage_counts().items():
            print(f"    {k.replace('applied_', '')}: {v}")
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
        if r.get("salary_text"):
            print(f"    salary: {r['salary_text']}")
        email = r.get("email") or {}
        if email.get("address"):
            print(f"    email: {email['address']} ({email['outcome']})")
        elif r.get("contact_emails"):
            print(f"    listed emails: {', '.join(r['contact_emails'])} (run: findmejob emails --job {r['id']})")
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


def cmd_benchmark(args) -> int:
    import json
    from .benchmark import run_benchmark
    result = run_benchmark(args.fixture)
    print(json.dumps(result.to_dict(), indent=2))
    return 1 if result.mismatches or result.zero_tolerance_failures else 0


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
    p = sub.add_parser("cv", help="build one personalized CV (Markdown + designed PDF)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", help="tracked job id or search text (strong fits only)")
    g.add_argument("--ad", help="path to a job ad text file, or - to read it from stdin")
    g.add_argument("--general", action="store_true", help="no job targeting - one general profile CV")
    p.add_argument("--title", default="", help="job title, when using --ad")
    p.add_argument("--company", default="", help="company name, when using --ad")
    p.add_argument("--style", choices=["designed", "classic"], default="designed")
    p.add_argument("--photo", help="JPEG photo for the designed header (default: profile.photo in config.json)")
    p.add_argument("--out", help="output directory (default: output/cvs)")
    p.set_defaults(fn=cmd_cv)
    p = sub.add_parser("apply", help="browser-assisted apply"); p.add_argument("--job", required=True)
    p.add_argument("--submit", action="store_true", help="allow final submit (still gated by config)")
    p.add_argument("--headless", action="store_true"); p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("emails", help="find verified contact emails (every method before 'none')")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--job", help="tracked job id or search text")
    g.add_argument("--all", action="store_true",
                   help="every applied/ready/shortlisted role whose hunt is missing, incomplete or failed")
    p.add_argument("--domain", default="", help="official company domain, e.g. example.com")
    p.add_argument("--confirmed", action="store_true",
                   help="the --domain was checked against the official site/LinkedIn")
    p.add_argument("--pages", help="JSON file of pages you opened: [{method,url,text}] (LinkedIn, registry...)")
    p.add_argument("--no-search", action="store_true", help="do not use a web search provider")
    p.add_argument("--outcome", choices=["sent", "failed", "pending"], help="record the follow-up result")
    p.add_argument("--proof", help="sent-message id or link (required with --outcome sent)")
    p.set_defaults(fn=cmd_emails)
    p = sub.add_parser("agencies", help="discover and validate recruitment agencies (any country/industry)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--country", help="country name or ISO code to search, e.g. 'New Zealand' or NZ")
    g.add_argument("--list", action="store_true", help="show tracked agencies")
    g.add_argument("--revalidate", action="store_true", help="re-run validation on tracked agencies")
    g.add_argument("--agency", help="agency id, name or domain: show its evidence, or record --outcome")
    p.add_argument("--city", default="", help="narrow to a city or region")
    p.add_argument("--industry", default="", help="industry or role family, e.g. 'nursing' or 'marketing'")
    p.add_argument("--country-code", default="", help="ISO 3166-1 alpha-2 code when the name cannot be resolved")
    p.add_argument("--methods", default="", help="comma list of discovery methods to run (default: all)")
    p.add_argument("--skip", default="", help="comma list of discovery methods to skip")
    p.add_argument("--pages", help="JSON file of pages or candidates you opened: [{url,text}] or [{name,website,source_url}]")
    p.add_argument("--no-search", action="store_true", help="do not use a web search provider")
    p.add_argument("--no-validate", action="store_true", help="discover only; validate later with --revalidate")
    p.add_argument("--limit", type=int, default=50, help="max agencies kept per run")
    p.add_argument("--status", choices=["discovered", "validated", "contacted", "no_verified_contact"],
                   help="filter for --list / --revalidate")
    p.add_argument("--for-country", default="", help="filter for --list / --revalidate")
    p.add_argument("--evidence", action="store_true", help="with --list: print every fact and its source")
    p.add_argument("--outcome", choices=["contacted"], help="with --agency: record that you contacted it")
    p.add_argument("--proof", help="sent-message id or link (required with --outcome contacted)")
    p.set_defaults(fn=cmd_agencies)
    p = sub.add_parser("status", help="tracker overview"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("list", help="list jobs"); p.add_argument("--status"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("pending", help="list pending questions"); p.set_defaults(fn=cmd_pending)
    p = sub.add_parser("answer", help="answer the oldest pending question"); p.add_argument("answer", nargs="+"); p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("chat", help="talk to the main agent"); p.add_argument("message", nargs="*"); p.set_defaults(fn=cmd_chat)
    p = sub.add_parser("tick", help="run queued worker tasks"); p.set_defaults(fn=cmd_tick)
    p = sub.add_parser("runtimes", help="list agent runtimes and capabilities"); p.set_defaults(fn=cmd_runtimes)
    p = sub.add_parser("benchmark", help="run an offline labeled qualification benchmark")
    p.add_argument("--fixture", required=True); p.set_defaults(fn=cmd_benchmark)
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

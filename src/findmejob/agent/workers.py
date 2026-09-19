"""Focused workers. Each does one job kind and reports an AgentResult."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import Config
from ..liveness import check_listing
from ..pipeline import load_profile, run_search, run_tailor, run_triage
from ..tracker import Tracker
from .contracts import AgentResult


def run_worker(kind: str, payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    fn = _WORKERS.get(kind)
    if not fn:
        return AgentResult(False, f"unknown worker kind: {kind}")
    return fn(payload, cfg, tracker)


def _source(payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    res = run_search(cfg, tracker)
    try:
        tri = run_triage(cfg, tracker)
    except FileNotFoundError:
        return AgentResult(True, f"fetched {res['fetched']}, {res['new']} new; no master CV yet, scoring skipped",
                           data=res, needs_user=["Add a master CV: findmejob ingest --cv your_cv.md"])
    needs = []
    for row in tracker.list_jobs(status="needs_input"):
        pass  # pending questions already recorded by triage
    return AgentResult(True,
                       f"fetched {res['fetched']}, {res['new']} new, shortlisted {tri['shortlisted']}, "
                       f"{tri['needs_review']} need review",
                       data={**res, **tri})


def _verify(payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    job_id = tracker.resolve_job_id(payload.get("job", ""))
    if not job_id:
        return AgentResult(False, f"no job matching {payload.get('job')!r}")
    job = tracker.get_job(job_id)
    if not job or not job.url:
        return AgentResult(False, "job has no URL to verify")

    # Use the same conservative GET/body check as the CLI. A reachable page
    # is not necessarily an open role: explicit closure text wins, ambiguous
    # HTTP failures stay unknown, and alive requires substantive apply evidence.
    liveness, detail = check_listing(job.url)
    tracker.set_liveness(job_id, liveness, detail)
    tri = run_triage(cfg, tracker, job_id=job_id)
    decision = tracker.qualification(job_id).get("decision")
    if liveness == "expired":
        summary = "listing expired"
    elif liveness == "alive":
        summary = "listing confirmed alive"
    else:
        summary = "listing liveness unknown"
    return AgentResult(
        True,
        f"{job.title} @ {job.company}: {summary} ({detail}); decision {decision}",
        data=tri,
    )


def _tailor(payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    res = run_tailor(cfg, tracker, payload.get("job", ""))
    if res.get("error"):
        return AgentResult(False, res["error"])
    needs = []
    if res["fidelity_warnings"]:
        needs.append(f"Review tailored CV for {res['job_id']}: terms not in master CV: "
                     + ", ".join(res["fidelity_warnings"][:6]))
    return AgentResult(True,
                       f"Tailored CV and short email ready for {res['job_id']}.\n"
                       f"CV: {res['cv']}\nEmail: {res['email']}",
                       data=res, needs_user=needs)


def _apply(payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    from ..browser.apply_flow import apply_to_job
    job_id = tracker.resolve_job_id(payload.get("job", ""))
    if not job_id:
        return AgentResult(False, f"no job matching {payload.get('job')!r}")
    job = tracker.get_job(job_id)
    profile = load_profile(cfg)
    assert job
    submit = bool(payload.get("submit", False))
    res = apply_to_job(job, profile, cfg, tracker, submit=submit)
    needs = []
    if res["status"] == "paused":
        needs.append(f"{job.title} @ {job.company} paused: {res.get('stop')}")
    return AgentResult(True, f"apply flow for {job_id}: {res['status']}", data=res,
                       needs_user=needs)


def _evidence(payload: dict, cfg: Config, tracker: Tracker) -> AgentResult:
    job_id = tracker.resolve_job_id(payload.get("job", ""))
    if not job_id:
        return AgentResult(False, f"no job matching {payload.get('job')!r}")
    out = cfg.output_dir
    found = [str(p) for p in sorted(out.rglob(f"*{job_id}*"))] if out.exists() else []
    tracker.add_event(job_id, "evidence", f"{len(found)} artifact(s)")
    return AgentResult(True, f"{len(found)} artifact(s) for {job_id}", data={"files": found})


_WORKERS = {
    "source": _source,
    "verify": _verify,
    "tailor": _tailor,
    "apply": _apply,
    "evidence": _evidence,
}

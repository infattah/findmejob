"""Produce profession-neutral qualification signals from persisted job evidence."""
from __future__ import annotations
import re
from typing import Any
from .evidence import evaluate_requirements
from .models import JobPosting, Profile
from .policy import check_job
from .qualification import QualificationSignals, signals_from_evidence
from .salary import normalize, parse_salary

_ACTION = re.compile(r"(?i)\b(?:lead|manage|own|build|create|develop|execute|optimi[sz]e|analy[sz]e|report|drive|launch|plan|deliver|responsible for)\b")
_WORD = re.compile(r"[a-z][a-z0-9+#.-]+")
_SENIOR = re.compile(r"(?i)\b(?:head|director|vp|vice president|chief)\b")
_JUNIOR = re.compile(r"(?i)\b(?:intern|junior|assistant|entry.level)\b")

_DOMAIN_REQUIREMENT = re.compile(r"(?i)\b(?:cybersecurity|fintech|finance|financial|payments?|banking|proptech|saas|software as a service|real estate|hospitality|fmcg|beauty|e-?commerce|retail|healthcare|pharma|b2b technology|creator tools?)\b")

def _domain_transferability(evidence) -> str:
    """Derive domain fit only from requirement-to-CV evidence.

    Generic evidence existence proves neither industry nor transferability. An explicit
    domain requirement that is ungrounded is a mismatch; preferred domain evidence can
    suggest transferability but can never create a critical gap.
    """
    domain_items = [i for i in evidence.items if _DOMAIN_REQUIREMENT.search(i.requirement)]
    hard = [i for i in domain_items if i.hard and not i.preferred]
    if hard and any(i.status != "strong" for i in hard):
        return "mismatch"
    if hard and all(i.status == "strong" for i in hard):
        return "direct"
    if domain_items:
        return "direct" if any(i.status == "strong" for i in domain_items) else "transferable"
    if any(i.status == "strong" for i in evidence.items):
        return "transferable"
    return "unknown"

def _tokens(text: str) -> set[str]:
    stop={"and","the","of","for","in","a","manager","specialist","lead","senior","junior"}
    return {x for x in _WORD.findall(text.lower()) if x not in stop}

def _phrase(keyword: str, title: str) -> bool:
    want=list(_tokens(keyword)); got=_tokens(title)
    return bool(want) and set(want)<=got

def _alignment(job: JobPosting, role_keywords: list[str]) -> tuple[str,str]:
    if not role_keywords: return "unknown","unknown"
    if any(_phrase(k, job.title) for k in role_keywords): return "direct","direct"
    title=_tokens(job.title)
    overlap=max((len(title & _tokens(k)) for k in role_keywords), default=0)
    return ("adjacent","transferable") if overlap else ("mismatch","mismatch")

def _seniority(profile: Profile, job: JobPosting) -> str:
    text=profile.all_facts_text()
    years=max([int(x) for x in re.findall(r"(?i)\b(\d{1,2})\s*\+?\s*years?", text)] or [0])
    if _SENIOR.search(job.title) and years < 6: return "stretch"
    if _JUNIOR.search(job.title) and years >= 5: return "overqualified"
    return "aligned"

def _salary(job: JobPosting, policy: dict[str,Any]) -> str:
    floor=int(policy.get("salary_floor") or 0)
    if not floor: return "pass"
    raw=parse_salary(job.salary_text or "")
    if not raw: return "review"
    n=normalize(raw, str(policy.get("currency") or ""), {k.upper():float(v) for k,v in (policy.get("exchange_rates") or {}).items()})
    if not n.converted or n.annual_min is None: return "review"
    return "pass" if n.annual_min >= floor else "block"

def build_signals(*, profile: Profile, job: JobPosting, policy: dict[str,Any], role_keywords: list[str], tracker) -> QualificationSignals:
    verdict=check_job(job, policy)
    location="pass"
    if any("location" in r.lower() for r in verdict.reasons): location="review"
    title,function=_alignment(job, role_keywords)
    evidence=evaluate_requirements(profile, job)
    verification=tracker.get_verification(job.id)
    employer={"verified":"verified","review":"partial"}.get(getattr(verification,"status",None),"unknown")
    row=next((r for r in tracker.list_jobs() if r["id"]==job.id), {})
    policy_signal=verdict.verdict
    if verdict.verdict=="review" and all(("salary" in r.lower() or "location" in r.lower()) for r in verdict.reasons):
        policy_signal="pass"
    return signals_from_evidence(
        policy=policy_signal, liveness=row.get("liveness","unknown"), title_alignment=title,
        function_alignment=function, domain_transferability=_domain_transferability(evidence),
        seniority=_seniority(profile, job), location=location, salary=_salary(job,policy),
        employer_context=employer, evidence=evidence,
        responsibility_evidence=bool(_ACTION.search(job.description or "")),
        critical_gaps=[f"hard requirement not proven: {i.requirement}" for i in evidence.items if i.hard and i.status!="strong"])

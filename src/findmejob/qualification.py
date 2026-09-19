"""Evidence-gated qualification, separate from broad discovery.

Discovery is intentionally recall-first.  This module is the precision gate: it
turns independently measured signals into one of six decisions without letting
a high keyword score erase uncertainty or a hard contradiction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

DECISIONS = (
    "strong", "plausible", "insufficient_evidence", "policy_review", "stale", "reject"
)


@dataclass(frozen=True)
class QualificationSignals:
    policy: str = "pass"                 # pass | review | block
    liveness: str = "unknown"            # alive | unknown | expired
    title_alignment: str = "unknown"     # direct | adjacent | mismatch | unknown
    function_alignment: str = "unknown"  # direct | transferable | mismatch | unknown
    domain_transferability: str = "unknown"  # direct | transferable | mismatch | unknown
    seniority: str = "unknown"           # aligned | stretch | overqualified | mismatch | unknown
    location: str = "unknown"            # pass | review | block | unknown
    salary: str = "unknown"              # pass | review | block | unknown
    employer_context: str = "unknown"    # verified | partial | unknown
    requirement_count: int = 0
    responsibility_evidence: bool = False
    hard_requirement_count: int = 0
    hard_requirement_strong: int = 0
    critical_gaps: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QualificationSignals":
        data = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        if "critical_gaps" in data:
            data["critical_gaps"] = tuple(data["critical_gaps"] or ())
        return cls(**data)


@dataclass(frozen=True)
class QualificationResult:
    decision: str
    actionable: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    coverage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hard_coverage(s: QualificationSignals) -> float:
    if not s.hard_requirement_count:
        return 1.0
    return min(1.0, s.hard_requirement_strong / s.hard_requirement_count)


def qualify(signals: QualificationSignals) -> QualificationResult:
    """Classify a discovered job with explicit precedence and uncertainty.

    `strong` is the only actionable decision.  It requires confirmed liveness,
    minimum evidence coverage, direct function/title fit, grounded employer
    context, no hard policy/location/salary contradiction, and no critical gap.
    Unknown evidence cannot be converted into a positive by a numeric fit score.
    """
    s = signals
    hard_cov = _hard_coverage(s)
    coverage = {
        "requirements": s.requirement_count,
        "responsibilities": s.responsibility_evidence,
        "hard_requirement_coverage": round(hard_cov, 3),
        "employer_context": s.employer_context,
        "liveness": s.liveness,
    }

    if s.liveness == "expired":
        return QualificationResult("stale", False, ("listing is expired or closed",), coverage)
    if s.policy == "block" or s.location == "block" or s.salary == "block":
        reason = "configured policy excludes this job"
        if s.location == "block": reason = "location is outside configured limits"
        if s.salary == "block": reason = "verified compensation is below the configured floor"
        return QualificationResult("reject", False, (reason,), coverage)
    if s.policy == "review":
        return QualificationResult("policy_review", False,
                                   ("employer/business policy needs a person to decide",), coverage)

    missing_coverage: list[str] = []
    if s.requirement_count == 0:
        missing_coverage.append("candidate requirements")
    if not s.responsibility_evidence:
        missing_coverage.append("role responsibilities")
    if s.employer_context == "unknown":
        missing_coverage.append("employer business context")
    if s.liveness == "unknown":
        missing_coverage.append("confirmed open application state")
    if s.title_alignment == "unknown" or s.function_alignment == "unknown":
        missing_coverage.append("role/function alignment")
    if missing_coverage:
        return QualificationResult(
            "insufficient_evidence", False,
            ("missing minimum evidence: " + ", ".join(missing_coverage),), coverage)

    mismatch = (
        s.title_alignment == "mismatch" or s.function_alignment == "mismatch"
        or s.domain_transferability == "mismatch" or s.seniority == "mismatch"
    )
    if mismatch or s.critical_gaps or hard_cov < 0.5:
        reasons = list(s.critical_gaps)
        if mismatch: reasons.append("material role, domain, or seniority mismatch")
        if hard_cov < 0.5: reasons.append("most hard requirements are not grounded in the CV")
        return QualificationResult("reject", False, tuple(reasons), coverage)

    direct = (
        s.title_alignment == "direct" and s.function_alignment == "direct"
        and s.domain_transferability in {"direct", "transferable"}
        and s.seniority == "aligned"
    )
    safe_edges = s.location == "pass" and s.salary == "pass"
    if direct and hard_cov >= 0.8 and s.employer_context == "verified" and safe_edges:
        return QualificationResult("strong", True,
                                   ("direct fit with sufficient grounded evidence",), coverage)

    reasons = []
    if s.title_alignment == "adjacent" or s.function_alignment == "transferable":
        reasons.append("adjacent or transferable role fit")
    if s.seniority in {"stretch", "overqualified"}:
        reasons.append(f"seniority is {s.seniority}")
    if hard_cov < 0.8:
        reasons.append("some hard requirements are not strongly grounded")
    if s.salary != "pass": reasons.append("salary needs review")
    if s.location != "pass": reasons.append("location needs review")
    if s.employer_context != "verified": reasons.append("employer context is only partial")
    return QualificationResult("plausible", False, tuple(reasons or ["fit is plausible but not actionable"]), coverage)


def signals_from_evidence(*, policy: str, liveness: str, title_alignment: str,
                          function_alignment: str, domain_transferability: str,
                          seniority: str, location: str, salary: str,
                          employer_context: str, evidence: Any,
                          responsibility_evidence: bool,
                          critical_gaps: Iterable[str] = ()) -> QualificationSignals:
    """Build normalized signals from adapters without profession-specific rules."""
    items = list(getattr(evidence, "items", ()) or ())
    hard = [item for item in items if getattr(item, "hard", False)]
    return QualificationSignals(
        policy=policy, liveness=liveness, title_alignment=title_alignment,
        function_alignment=function_alignment,
        domain_transferability=domain_transferability, seniority=seniority,
        location=location, salary=salary, employer_context=employer_context,
        requirement_count=len(items), responsibility_evidence=responsibility_evidence,
        hard_requirement_count=len(hard),
        hard_requirement_strong=sum(getattr(item, "status", "") == "strong" for item in hard),
        critical_gaps=tuple(critical_gaps),
    )

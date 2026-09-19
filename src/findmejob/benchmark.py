"""Offline labeled benchmark for qualification changes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .qualification import QualificationSignals, qualify
from .models import JobPosting, Profile


@dataclass(frozen=True)
class BenchmarkResult:
    total: int
    correct: int
    actionable_tp: int
    actionable_fp: int
    actionable_fn: int
    zero_tolerance_failures: int
    mismatches: tuple[dict[str, Any], ...]

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def actionable_precision(self) -> float:
        d = self.actionable_tp + self.actionable_fp
        return self.actionable_tp / d if d else 0.0

    @property
    def actionable_recall(self) -> float:
        d = self.actionable_tp + self.actionable_fn
        return self.actionable_tp / d if d else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total, "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "actionable_precision": round(self.actionable_precision, 4),
            "actionable_recall": round(self.actionable_recall, 4),
            "zero_tolerance_failures": self.zero_tolerance_failures,
            "mismatches": list(self.mismatches),
        }


def run_benchmark(path: str | Path) -> BenchmarkResult:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    mismatches: list[dict[str, Any]] = []
    tp = fp = fn = zt = correct = 0
    for row in rows:
        result = qualify(QualificationSignals.from_dict(row["signals"]))
        expected = row["expected"]
        if result.decision == expected:
            correct += 1
        else:
            mismatches.append({"id": row["id"], "expected": expected,
                               "actual": result.decision, "reasons": list(result.reasons)})
        expected_actionable = expected == "strong"
        if result.actionable and expected_actionable: tp += 1
        elif result.actionable: fp += 1
        elif expected_actionable: fn += 1
        if row.get("zero_tolerance") and result.actionable:
            zt += 1
    return BenchmarkResult(len(rows), correct, tp, fp, fn, zt, tuple(mismatches))


def run_replay_benchmark(path: str | Path) -> BenchmarkResult:
    """Replay labeled posting/profile/state records through signal production.

    Fixtures remain curated and cannot prove field performance; unlike the signal-only
    benchmark, this catches adapter regressions in policy, evidence, alignment and state.
    """
    from .signal_adapter import build_signals
    from .tracker import Tracker
    import tempfile
    rows=json.loads(Path(path).read_text(encoding="utf-8")); derived=[]
    for row in rows:
        with tempfile.TemporaryDirectory() as td:
            tracker=Tracker(Path(td)/"replay.db")
            job=JobPosting.from_dict(row["job"]); tracker.upsert_job(job, verdict="pass")
            tracker.set_liveness(job.id,row.get("liveness","unknown"),"benchmark fixture")
            verification=row.get("verification")
            if verification:
                from .verification import CompanyVerification
                tracker.set_verification(job.id,CompanyVerification.from_dict(verification))
            profile=Profile.from_dict(row["profile"]) if hasattr(Profile,"from_dict") else Profile(raw_text=row["profile"].get("raw_text",""), skills=row["profile"].get("skills",[]), headline=row["profile"].get("headline",""), summary=row["profile"].get("summary",""))
            sig=build_signals(profile=profile,job=job,policy=row.get("policy",{}),role_keywords=row.get("role_keywords",[]),tracker=tracker)
            derived.append({"id":row["id"],"expected":row["expected"],"signals":__import__("dataclasses").asdict(sig),"zero_tolerance":row.get("zero_tolerance",False)})
            tracker.close()
    tmp=Path(str(path)+".derived.tmp")
    try: tmp.write_text(json.dumps(derived)); return run_benchmark(tmp)
    finally: tmp.unlink(missing_ok=True)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run a labeled qualification benchmark")
    parser.add_argument("fixture")
    args = parser.parse_args(argv)
    print(json.dumps(run_benchmark(args.fixture).to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

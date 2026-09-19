"""Offline labeled benchmark for qualification changes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .qualification import QualificationSignals, qualify


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


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run a labeled qualification benchmark")
    parser.add_argument("fixture")
    args = parser.parse_args(argv)
    print(json.dumps(run_benchmark(args.fixture).to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

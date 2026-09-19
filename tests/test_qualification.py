from __future__ import annotations

import json
import unittest
from pathlib import Path

from findmejob.benchmark import run_benchmark
from findmejob.liveness import check_listing
from findmejob.models import JobPosting
from findmejob.policy import check_job
from findmejob.qualification import QualificationSignals, qualify

FIXTURE = Path(__file__).parent / "fixtures" / "trials_1_5_qualification.json"


class QualificationModelTests(unittest.TestCase):
    def test_only_strong_is_actionable(self):
        rows = json.loads(FIXTURE.read_text())
        for row in rows:
            result = qualify(QualificationSignals.from_dict(row["signals"]))
            self.assertEqual(result.actionable, result.decision == "strong", row["id"])

    def test_uncertainty_never_becomes_strong(self):
        result = qualify(QualificationSignals(
            liveness="unknown", title_alignment="direct", function_alignment="direct",
            domain_transferability="direct", seniority="aligned", location="pass",
            salary="pass", employer_context="verified", requirement_count=4,
            responsibility_evidence=True))
        self.assertEqual("insufficient_evidence", result.decision)

    def test_trials_1_5_offline_benchmark(self):
        result = run_benchmark(FIXTURE)
        self.assertEqual(20, result.total)
        self.assertEqual(20, result.correct)
        self.assertEqual(1.0, result.actionable_precision)
        self.assertEqual(1.0, result.actionable_recall)
        self.assertEqual(0, result.zero_tolerance_failures)


class TrialFiveBoundaryTests(unittest.TestCase):
    def test_applications_are_now_closed_overrides_submit_marker(self):
        status, _ = check_listing("https://example.test/job", opener=lambda *_: (
            200, "Submit application. Applications are now closed."))
        self.assertEqual("expired", status)

    def test_edenred_style_business_is_restricted_by_context(self):
        job = JobPosting(
            title="Performance Marketing Manager", company="Example Benefits UAE",
            description="We provide payroll services, corporate payments, money transfer and card services to employers.")
        verdict = check_job(job, {"sector_exclusions": ["payroll services", "corporate payments", "money transfer", "card services"]})
        self.assertEqual("block", verdict.verdict)

    def test_deliverect_style_restaurant_saas_is_not_hospitality_employer(self):
        job = JobPosting(
            title="Regional Marketing Specialist", company="Delivery Cloud Tech",
            description="We are a SaaS platform serving restaurants and hospitality operators.")
        verdict = check_job(job, {"sector_exclusions": ["hotel", "hospitality"]})
        self.assertNotEqual("block", verdict.verdict)

    def test_direct_hospitality_employer_still_blocks(self):
        job = JobPosting(
            title="Digital Marketing Manager", company="Example Hotels and Resorts",
            description="We operate hotels and resorts across the region.")
        verdict = check_job(job, {"sector_exclusions": ["hotel", "hospitality"]})
        self.assertEqual("block", verdict.verdict)


if __name__ == "__main__":
    unittest.main()

class ReplayAdapterBenchmarkTests(unittest.TestCase):
    def test_replay_exercises_signal_adapter(self):
        from findmejob.benchmark import run_replay_benchmark
        result=run_replay_benchmark(Path(__file__).parent/'fixtures'/'qualification_replay.json')
        self.assertEqual(3,result.correct)
        self.assertEqual(0,result.zero_tolerance_failures)

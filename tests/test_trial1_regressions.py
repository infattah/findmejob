import tempfile
import unittest
from pathlib import Path

from findmejob.config import Config
from findmejob.evidence import evaluate_requirements
from findmejob.liveness import check_listing
from findmejob.models import Experience, JobPosting, Profile
from findmejob.pipeline import run_triage
from findmejob.policy import check_job
from findmejob.tracker import Tracker


class TrialOneRegressions(unittest.TestCase):
    def test_remote_india_does_not_bypass_uae_location(self):
        job = JobPosting(title="Growth Manager", company="Platinumlist", location="India", remote=True)
        result = check_job(job, {"locations_include": ["UAE", "Oman", "Qatar", "Saudi Arabia", "Remote"]})
        self.assertEqual(result.verdict, "review")
        self.assertIn("not in include list", result.reasons[0])

    def test_explicit_seven_years_satisfies_three_to_five(self):
        profile = Profile(summary="Growth marketer with 7+ years of experience")
        job = JobPosting(title="Manager", company="Acme", description="Qualifications\n- Requires 3-5+ years of performance marketing experience")
        item = evaluate_requirements(profile, job).items[0]
        self.assertEqual(item.status, "strong")
        self.assertIn("7+ years", item.evidence[0])

    def test_hard_language_is_not_generic_partial(self):
        profile = Profile(summary="International marketer and team leader", education=[])
        job = JobPosting(title="Marketing Manager", company="Platinumlist", description="Requirements\n- Fluent written Arabic is required")
        item = evaluate_requirements(profile, job).items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "missing")
        self.assertEqual(item.evidence, [])

    def test_http_200_without_apply_evidence_is_unknown(self):
        body = "<html><body>" + ("Company careers and culture. " * 30) + "</body></html>"
        self.assertEqual(check_listing("https://example/jobs/1", lambda u, t: (200, body))[0], "unknown")

    def test_explicit_apply_evidence_is_alive(self):
        body = "<html><body>" + ("Role details. " * 30) + "<button>Apply for this job</button></body></html>"
        status, detail = check_listing("https://example/jobs/1", lambda u, t: (200, body))
        self.assertEqual(status, "alive")
        self.assertIn("page says", detail)

    def test_salary_review_keeps_score_and_hard_gap_constrains(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "cv.md").write_text("# A Person\n## Summary\nGrowth marketer\n## Skills\n- SEO\n", encoding="utf-8")
            cfg = Config(root=root, raw={
                "profile": {"master_cv": "cv.md"},
                "search": {"role_keywords": ["marketing manager"]},
                "policy": {"salary_floor": 50000, "currency": "USD", "min_fit_score": 0},
                "paths": {"db": "jobs.db", "output": "out", "cache": "cache"},
            })
            tracker = Tracker(root / "jobs.db")
            job = JobPosting(title="Marketing Manager", company="Acme", description="Requirements\n- Fluent written Arabic is required")
            tracker.upsert_job(job, verdict="review")
            tracker.conn.commit()
            run_triage(cfg, tracker)
            row = tracker.list_jobs()[0]
            self.assertIsNotNone(row["score"])
            self.assertEqual(row["status"], "needs_input")
            self.assertIn("salary not stated", row["notes"])
            self.assertIn("hard requirement not proven", row["notes"])
            tracker.close()


if __name__ == "__main__":
    unittest.main()

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

    def test_domain_rules_do_not_change_discovery_input(self):
        docs = (Path(__file__).parent.parent / "docs" / "configuration.md").read_text()
        self.assertIn("start with simple target role names or keywords", docs)
        self.assertIn("Those checks run after\ndiscovery", docs)

    def test_remote_india_does_not_bypass_uae_location(self):
        job = JobPosting(title="Growth Manager", company="Platinumlist", location="India", remote=True)
        result = check_job(job, {"locations_include": ["UAE", "Oman", "Qatar", "Saudi Arabia", "Remote"]})
        self.assertEqual(result.verdict, "review")
        self.assertIn("not in include list", result.reasons[0])

    def test_explicit_seven_years_satisfies_three_to_five(self):
        profile = Profile(summary="Growth marketer with 7+ years of performance marketing experience")
        job = JobPosting(title="Manager", company="Acme", description="Qualifications\n- Requires 3-5+ years of performance marketing experience")
        item = evaluate_requirements(profile, job).items[0]
        self.assertEqual(item.status, "strong")
        self.assertIn("7+ years", item.evidence[0])


    def test_unrelated_domain_years_do_not_satisfy_b2b_saas_requirement(self):
        profile = Profile(
            summary="Growth marketer with 9+ years in consumer retail",
            experiences=[Experience(role="Growth Lead", company="RetailCo",
                                    bullets=["Led ecommerce acquisition and merchandising"])],
        )
        job = JobPosting(title="Demand Generation Lead", company="Acme",
                         description="Requirements\n- 5+ years of B2B SaaS demand generation experience")
        item = evaluate_requirements(profile, job).items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "missing")

    def test_same_summary_separate_claims_do_not_bleed_domain(self):
        profile = Profile(summary="9+ years in consumer retail. B2B SaaS demand generation specialist.")
        job = JobPosting(title="Lead", company="Acme", description="Requirements\n- 5+ years of B2B SaaS demand generation")
        self.assertEqual(evaluate_requirements(profile, job).items[0].status, "partial")

    def test_same_raw_line_separate_claims_do_not_bleed_domain(self):
        profile = Profile(raw_text="9+ years in consumer retail. B2B SaaS demand generation specialist.")
        job = JobPosting(title="Lead", company="Acme", description="Requirements\n- 5+ years of B2B SaaS demand generation")
        self.assertEqual(evaluate_requirements(profile, job).items[0].status, "partial")

    def test_role_context_does_not_donate_domain_to_numeric_bullet(self):
        profile = Profile(experiences=[Experience(role="B2B SaaS Demand Generation Lead", company="Acme", bullets=["9+ years in consumer retail"])])
        job = JobPosting(title="Lead", company="NextCo", description="Requirements\n- 5+ years of B2B SaaS demand generation")
        self.assertEqual(evaluate_requirements(profile, job).items[0].status, "partial")

    def test_split_requirement_keeps_domain_attached_to_years(self):
        profile = Profile(summary="9+ years in consumer retail")
        job = JobPosting(title="Lead", company="Acme", description="Requirements\n- 5+ years of experience. B2B SaaS demand generation expertise required")
        item = evaluate_requirements(profile, job).items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "missing")

    def test_matching_domain_in_one_clause_remains_strong(self):
        profile = Profile(summary="7+ years in B2B SaaS demand generation. Also led retail projects.")
        job = JobPosting(title="Lead", company="Acme", description="Requirements\n- 5+ years of B2B SaaS demand generation")
        self.assertEqual(evaluate_requirements(profile, job).items[0].status, "strong")

    def test_role_domain_without_tied_duration_preserves_recall(self):
        profile = Profile(experiences=[Experience(role="B2B SaaS Demand Generation Lead", company="Acme", bullets=["Owned pipeline and lifecycle programs"])])
        job = JobPosting(title="Lead", company="NextCo", description="Requirements\n- 5+ years of B2B SaaS demand generation")
        self.assertEqual(evaluate_requirements(profile, job).items[0].status, "partial")

    def test_matching_domain_years_satisfy_requirement(self):
        profile = Profile(summary="7+ years of B2B SaaS demand generation experience")
        job = JobPosting(title="Demand Generation Lead", company="Acme",
                         description="Requirements\n- 5+ years of B2B SaaS demand generation experience")
        item = evaluate_requirements(profile, job).items[0]
        self.assertEqual(item.status, "strong")
        self.assertIn("domain-matched", item.evidence[0])

    def test_domain_evidence_without_numeric_years_is_partial(self):
        profile = Profile(experiences=[Experience(
            role="B2B SaaS Demand Generation Manager", company="Acme",
            bullets=["Owned demand generation campaigns and pipeline programs"])])
        job = JobPosting(title="Demand Generation Lead", company="NextCo",
                         description="Requirements\n- 5+ years of B2B SaaS demand generation experience")
        item = evaluate_requirements(profile, job).items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "partial")
        self.assertIn("without grounded duration", item.evidence[0])

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
            pending = tracker.pending()
            self.assertEqual(len(pending), 1)
            self.assertIn("hard requirement not proven: Fluent written Arabic is required",
                          pending[0]["question"])
            tracker.close()


if __name__ == "__main__":
    unittest.main()


class TrialThreeRecommendationQuality(unittest.TestCase):
    def _cfg(self, root):
        (root / "cv.md").write_text(
            "# A Person\n## Summary\nGrowth marketer with 7+ years in paid acquisition and automation\n"
            "## Skills\n- Digital marketing\n- Marketing automation\n- Paid media\n", encoding="utf-8")
        return Config(root=root, raw={
            "profile": {"master_cv": "cv.md"},
            "search": {"role_keywords": ["growth marketing", "marketing automation", "digital marketing"]},
            "policy": {"min_fit_score": 45},
            "paths": {"db": "jobs.db", "output": "out", "cache": "cache"},
        })

    def test_title_only_digital_role_is_review_not_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = self._cfg(root); tracker = Tracker(root / "jobs.db")
            job = JobPosting(title="Assistant Manager - Digital Marketing",
                             company="Dubai Holding", location="Dubai",
                             description="Digital marketing opportunity in Dubai.")
            tracker.upsert_job(job, verdict="pass"); tracker.conn.commit()
            result = run_triage(cfg, tracker)
            row = tracker.list_jobs()[0]
            self.assertEqual(result["shortlisted"], 0)
            self.assertEqual(row["status"], "needs_input")
            self.assertIn("insufficient job evidence", row["notes"])
            tracker.close()

    def test_adjacent_content_operations_role_is_not_shortlisted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = self._cfg(root); tracker = Tracker(root / "jobs.db")
            job = JobPosting(title="Content Automation Strategist", company="Ounass", location="Dubai",
                             description=("Own bilingual luxury editorial operations and Contentful. " * 8))
            tracker.upsert_job(job, verdict="pass"); tracker.conn.commit()
            result = run_triage(cfg, tracker)
            self.assertEqual(result["shortlisted"], 0)
            self.assertLess(tracker.list_jobs()[0]["score"], 45)
            tracker.close()

class TrialThreeEvidenceCompletenessBoundaries(unittest.TestCase):
    def _cfg(self, root):
        (root / "cv.md").write_text(
            "# Candidate\n## Summary\nGrowth marketer with 7+ years\n## Skills\n- Google Ads\n- Paid social\n- Analytics\n- CRO\n",
            encoding="utf-8")
        return Config(root=root, raw={
            "profile": {"master_cv": "cv.md"},
            "search": {"role_keywords": ["growth marketing"]},
            "policy": {"min_fit_score": 45},
            "paths": {"db": "jobs.db", "output": "out", "cache": "cache"},
        })

    def test_concise_specific_listing_can_be_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = self._cfg(root); tracker = Tracker(root / "jobs.db")
            job = JobPosting(title="Growth Marketing Manager", company="Acme", location="Dubai",
                description="Lead Google Ads, paid social, analytics and CRO for UAE ecommerce. Requires 5+ years. Dubai hybrid, reporting to CMO.")
            self.assertLess(len(job.description.split()), 30)
            tracker.upsert_job(job, verdict="pass"); tracker.conn.commit()
            result = run_triage(cfg, tracker)
            row = tracker.list_jobs()[0]
            self.assertEqual(result["shortlisted"], 1)
            self.assertEqual(row["status"], "shortlisted")
            tracker.close()

    def test_wordy_title_repetition_remains_insufficient(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = self._cfg(root); tracker = Tracker(root / "jobs.db")
            job = JobPosting(title="Growth Marketing Manager", company="Acme", location="Dubai",
                description=("Growth marketing opportunity. " * 20))
            tracker.upsert_job(job, verdict="pass"); tracker.conn.commit()
            result = run_triage(cfg, tracker)
            row = tracker.list_jobs()[0]
            self.assertEqual(result["shortlisted"], 0)
            self.assertEqual(row["status"], "needs_input")
            self.assertIn("insufficient job evidence", row["notes"])
            tracker.close()

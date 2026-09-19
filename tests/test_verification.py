import tempfile
import unittest
from pathlib import Path

from findmejob.models import JobPosting
from findmejob.tracker import Tracker
from findmejob.verification import (
    ApplicationRoute, CompanyVerification, Evidence, verification_from_json,
)


class TestCompanyVerification(unittest.TestCase):
    def verified(self):
        return CompanyVerification(
            company="Example Co", status="verified", official_domain="example.com",
            evidence=[
                Evidence("official_website", "https://example.com"),
                Evidence("linkedin", "https://www.linkedin.com/company/example"),
                Evidence("ats", "https://jobs.example.com/openings"),
            ],
            routes=[
                ApplicationRoute("careers", "https://example.com/careers",
                                 "https://example.com", verified=True),
                ApplicationRoute("ats", "https://jobs.example.com/123",
                                 "https://example.com/careers", verified=True),
            ],
        )

    def test_three_signal_verified_rule_and_route_priority(self):
        result = self.verified()
        self.assertEqual(result.validate(), [])
        self.assertEqual(result.best_route().kind, "ats")

    def test_unknown_is_preserved_without_evidence(self):
        result = verification_from_json({"company": "Unclear Ltd", "status": "unknown"})
        self.assertEqual(result.status, "unknown")
        self.assertIsNone(result.best_route())

    def test_verified_requires_corroboration(self):
        result = CompanyVerification(
            company="Thin", status="verified",
            evidence=[Evidence("official_website", "https://thin.example"),
                      Evidence("linkedin", "https://linkedin.com/company/thin")])
        self.assertTrue(any("corroboration" in e for e in result.validate()))

    def test_rejects_guessed_or_unsourced_contacts(self):
        result = CompanyVerification(
            company="Example", official_domain="example.com",
            routes=[ApplicationRoute("email", "jobs@other.example", "", verified=True)])
        errors = result.validate()
        self.assertTrue(any("source URL" in e for e in errors))
        self.assertTrue(any("inconsistent" in e for e in errors))

    def test_risks_cannot_be_silently_verified(self):
        result = self.verified()
        result.risks = ["TLS certificate mismatch on tracking redirect"]
        self.assertTrue(any("review status" in e for e in result.validate()))

    def test_tracker_round_trip(self):
        tracker = Tracker(Path(tempfile.mkdtemp()) / "jobs.db")
        job = JobPosting(title="Marketer", company="Example Co", url="https://example.com/job")
        tracker.upsert_job(job)
        tracker.set_verification(job.id, self.verified())
        row = tracker.list_jobs()[0]
        self.assertEqual(row["verification"]["status"], "verified")
        self.assertEqual(row["verification"]["route"], "https://jobs.example.com/123")

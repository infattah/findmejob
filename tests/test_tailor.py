import unittest
from pathlib import Path

from findmejob.models import JobPosting
from findmejob.profile import parse_master_cv
from findmejob.tailor import check_fidelity, draft_email, rank_skills, render_cv_markdown

SAMPLE = Path(__file__).parent.parent / "sample_data" / "master_cv.example.md"


class TestTailor(unittest.TestCase):
    def setUp(self):
        self.profile = parse_master_cv(SAMPLE.read_text())
        self.job = JobPosting(title="Lifecycle Marketing Manager", company="Acme",
                              description="lifecycle email marketing retention SQL")

    def test_rank_skills_prefers_job_keywords(self):
        ranked = rank_skills(self.profile, self.job)
        self.assertEqual(ranked[0], "Lifecycle and email marketing")

    def test_render_contains_only_master_facts(self):
        cv = render_cv_markdown(self.profile, self.job)
        warnings = check_fidelity(self.profile.all_facts_text(), cv)
        self.assertEqual(warnings, [])

    def test_fidelity_flags_invention(self):
        warnings = check_fidelity(self.profile.all_facts_text(),
                                  "# Alex Example\n\nWorked at Globex on Kubernetes, grew 900%.")
        self.assertIn("Globex", warnings)
        self.assertIn("900%", warnings)

    def test_email_is_short(self):
        subject, body = draft_email(self.profile, self.job)
        self.assertIn("Lifecycle Marketing Manager", subject)
        self.assertLess(len(body.splitlines()), 18)
        self.assertIn("alex@example.com", body)


if __name__ == "__main__":
    unittest.main()

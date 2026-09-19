import unittest

from findmejob.evidence import (evaluate_requirements, extract_requirements,
                                render_report_markdown)
from findmejob.models import Education, Experience, JobPosting, Profile

DESC = """About the role
We are growing the team.

Requirements
- 4+ years of experience in performance marketing
- Proficiency with Google Ads and Meta Ads
- Bachelor's degree in Marketing or related field
- Experience with Kubernetes cluster administration

Benefits
- Health insurance
"""


def profile():
    return Profile(
        full_name="Alex Example",
        skills=["Google Ads", "Meta Ads"],
        experiences=[Experience(
            role="Performance Marketing Manager", company="Acme",
            bullets=["Ran Google Ads and Meta Ads campaigns for 5 years"])],
        education=[],
    )


class TestExtraction(unittest.TestCase):
    def test_finds_requirement_bullets(self):
        reqs = extract_requirements(DESC)
        self.assertEqual(len(reqs), 4)
        self.assertIn("4+ years of experience in performance marketing", reqs)
        self.assertNotIn("Health insurance", reqs)

    def test_empty_description(self):
        self.assertEqual(extract_requirements(""), [])


class TestEvaluation(unittest.TestCase):
    def test_strong_partial_missing(self):
        report = evaluate_requirements(profile(), JobPosting(
            title="PMM", company="Acme", description=DESC))
        by_req = {i.requirement: i.status for i in report.items}
        self.assertEqual(by_req["Proficiency with Google Ads and Meta Ads"], "strong")
        self.assertEqual(
            by_req["4+ years of experience in performance marketing"], "strong")
        self.assertEqual(
            by_req["Experience with Kubernetes cluster administration"], "missing")

    def test_missing_means_no_cv_evidence(self):
        p = profile()
        p.education = [Education(degree="BSc Computer Science", school="Uni")]
        report = evaluate_requirements(p, JobPosting(
            title="PMM", company="Acme",
            description="Requirements\n- Master's degree in Marketing\n"))
        item = report.items[0]
        self.assertEqual(item.status, "missing")

    def test_report_renders_counts(self):
        report = evaluate_requirements(profile(), JobPosting(
            title="PMM", company="Acme", description=DESC))
        md = render_report_markdown(report, score=70, score_reasons=["skills matched"])
        self.assertIn("strong", md)
        self.assertIn("MISSING", md)
        self.assertIn("Kubernetes", md)


if __name__ == "__main__":
    unittest.main()

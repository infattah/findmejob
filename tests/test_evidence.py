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

class TestTrialFourEvidenceRegressions(unittest.TestCase):
    def test_generic_seven_years_plus_matching_paid_domain_satisfies_range(self):
        p = Profile(summary="Marketing professional with 7+ years of experience.",
                    skills=["Paid media", "Meta Ads", "Google Ads", "A/B testing"])
        job = JobPosting(title="Performance Marketing Specialist", company="instashop",
                         description="Qualifications\n- 3-5 years of performance marketing experience")
        item = evaluate_requirements(p, job).items[0]
        self.assertEqual(item.status, "strong")

    def test_domain_bound_unrelated_years_do_not_transfer(self):
        p = Profile(summary="7+ years in consumer retail.", skills=["Paid media", "Google Ads"])
        job = JobPosting(title="Lead", company="Acme",
                         description="Qualifications\n- 5+ years of B2B SaaS demand generation experience")
        self.assertNotEqual(evaluate_requirements(p, job).items[0].status, "strong")

    def test_company_history_duration_is_not_candidate_requirement(self):
        text = ("About us\nDelivery Hero has been delivering for 18 years across global markets.\n"
                "Requirements\n- 4+ years of CRM marketing experience")
        reqs = extract_requirements(text)
        self.assertNotIn("Delivery Hero has been delivering for 18 years across global markets.", reqs)
        self.assertIn("4+ years of CRM marketing experience", reqs)

    def test_we_have_operated_for_years_is_not_candidate_requirement(self):
        self.assertEqual(extract_requirements(
            "About us. We have operated for 12 years serving local merchants."), [])

class TestIndependentReviewCompanyHistoryBoundaries(unittest.TestCase):
    def test_natural_company_history_durations_are_not_requirements(self):
        histories = (
            "For 18 years, Delivery Hero has been delivering food worldwide.",
            "Founded 18 years ago, Delivery Hero serves global markets.",
            "About us. Our company has 18 years of experience serving merchants.",
        )
        for text in histories:
            with self.subTest(text=text):
                self.assertEqual(extract_requirements(text), [])

    def test_real_candidate_year_requirements_remain(self):
        descriptions = (
            "Requirements\n- 5+ years of performance marketing experience",
            "What you'll need\n- At least 3 years of experience in CRM",
            "The candidate must have 4 years of paid media experience.",
        )
        for text in descriptions:
            with self.subTest(text=text):
                self.assertTrue(extract_requirements(text))

class TestIndependentReviewCompanyHistoryBoundaries(unittest.TestCase):
    def test_natural_company_history_durations_are_not_requirements(self):
        histories = ("For 18 years, Delivery Hero has been delivering food worldwide.", "Founded 18 years ago, Delivery Hero serves global markets.", "About us. Our company has 18 years of experience serving merchants.")
        for text in histories:
            with self.subTest(text=text):
                self.assertEqual(extract_requirements(text), [])

    def test_real_candidate_year_requirements_remain(self):
        descriptions = ("Requirements\n- 5+ years of performance marketing experience", "What you'll need\n- At least 3 years of experience in CRM", "The candidate must have 4 years of paid media experience.")
        for text in descriptions:
            with self.subTest(text=text):
                self.assertTrue(extract_requirements(text))

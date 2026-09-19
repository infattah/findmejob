import unittest
from pathlib import Path

from findmejob.models import JobPosting
from findmejob.profile import parse_master_cv
from findmejob.scoring import score_fit

SAMPLE = Path(__file__).parent.parent / "sample_data" / "master_cv.example.md"


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.profile = parse_master_cv(SAMPLE.read_text())

    def test_strong_fit_scores_higher(self):
        strong = JobPosting(
            title="Growth Marketing Manager", company="Acme", remote=True,
            description="Paid acquisition, lifecycle email, conversion rate optimization, SQL, e-commerce growth.")
        weak = JobPosting(title="Civil Engineer", company="BuildCo",
                          description="Structural design, concrete, site supervision.")
        kw = ["growth marketing"]
        self.assertGreater(score_fit(self.profile, strong, kw).score,
                           score_fit(self.profile, weak, kw).score)

    def test_score_bounds(self):
        job = JobPosting(title="Growth Marketing Manager", company="Acme", remote=True,
                         description="paid acquisition lifecycle email conversion SQL dashboards e-commerce")
        score = score_fit(self.profile, job, ["growth marketing"]).score
        self.assertTrue(0 <= score <= 100)

    def test_single_generic_word_does_not_promote_adjacent_content_role(self):
        job = JobPosting(
            title="Content Automation Strategist", company="Ounass", location="Dubai",
            description=("Own luxury bilingual editorial operations, Contentful workflows, "
                         "content governance, taxonomy and publishing automation."),
        )
        result = score_fit(self.profile, job,
                           ["growth marketing", "marketing automation", "digital marketing"])
        self.assertLess(result.score, 45)
        self.assertIn("adjacent", result.reasons[-1])

    def test_full_target_phrase_keeps_strong_role_visible(self):
        job = JobPosting(
            title="Growth Marketing Manager (MEA)", company="iHerb", location="Dubai",
            description="Lead paid media, ecommerce acquisition, lifecycle and regional growth strategy.",
        )
        result = score_fit(self.profile, job, ["growth marketing"])
        self.assertTrue(any("title matches" in r for r in result.reasons))


if __name__ == "__main__":
    unittest.main()

class TestTargetTitleBoundaries(unittest.TestCase):
    def setUp(self):
        self.profile = parse_master_cv(SAMPLE.read_text())

    def test_inserted_specialism_matches_full_target(self):
        job = JobPosting(title="Digital & Performance Marketing Manager", company="Acme",
                         description="Lead Google Ads and paid social performance across UAE ecommerce.")
        result = score_fit(self.profile, job, ["digital marketing"])
        self.assertTrue(any("title matches" in r for r in result.reasons))

    def test_connectors_do_not_break_full_target(self):
        job = JobPosting(title="Growth and Performance Marketing Lead", company="Acme",
                         description="Lead growth and paid media.")
        result = score_fit(self.profile, job, ["growth marketing"])
        self.assertTrue(any("title matches" in r for r in result.reasons))

    def test_one_generic_target_token_still_does_not_match(self):
        job = JobPosting(title="Content Automation Strategist", company="Ounass",
                         description="Own editorial content workflows and publishing automation.")
        result = score_fit(self.profile, job, ["marketing automation"])
        self.assertFalse(any("title matches" in r for r in result.reasons))

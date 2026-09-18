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


if __name__ == "__main__":
    unittest.main()

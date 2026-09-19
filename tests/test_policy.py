lib iimport unittest

from findmejob.models import JobPosting
from findmejob.policy import check_job

POLICY = {
    "salary_floor": 60000,
    "currency": "USD",
    "locations_include": ["remote", "dubai"],
    "locations_exclude": [],
    "sector_exclusions": ["sector-you-avoid"],
    "title_exclude": ["intern"],
}


class TestPolicy(unittest.TestCase):
    def job(self, **kw):
        base = dict(title="Growth Marketing Manager", company="Acme", location="Dubai",
                    salary_text="USD 80,000 per year")
        base.update(kw)
        return JobPosting(**base)

    def test_pass(self):
        self.assertEqual(check_job(self.job(), POLICY).verdict, "pass")

    def test_title_block(self):
        r = check_job(self.job(title="Marketing Intern"), POLICY)
        self.assertEqual(r.verdict, "block")

    def test_sector_block(self):
        r = check_job(self.job(description="We work in the sector-you-avoid space."), POLICY)
        self.assertEqual(r.verdict, "block")

    def test_low_salary_review(self):
        r = check_job(self.job(salary_text="$40,000 per year"), POLICY)
        self.assertEqual(r.verdict, "review")

    def test_wrong_location_review(self):
        r = check_job(self.job(location="Cairo"), POLICY)
        self.assertEqual(r.verdict, "review")

    def test_remote_without_matching_hiring_location_needs_review(self):
        r = check_job(self.job(location="Anywhere", remote=True), POLICY)
        self.assertEqual(r.verdict, "review")

if __name__ == "__main__":
    unittest.main()

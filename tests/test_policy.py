import unittest

from findmejob.models import JobPosting
from findmejob.policy import check_job, parse_salary_floor

POLICY = {
    "salary_floor": 60000,
    "locations_include": ["remote", "dubai"],
    "locations_exclude": [],
    "sector_exclusions": ["sector-you-avoid"],
    "title_exclude": ["intern"],
}


class TestPolicy(unittest.TestCase):
    def job(self, **kw):
        base = dict(title="Growth Marketing Manager", company="Acme", location="Dubai",
                    salary_text="$80,000 per year")
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

    def test_remote_ok(self):
        r = check_job(self.job(location="Anywhere", remote=True), POLICY)
        self.assertEqual(r.verdict, "pass")

    def test_salary_parse(self):
        self.assertEqual(parse_salary_floor("$70,000 - $90,000 per year"), 70000)
        self.assertEqual(parse_salary_floor("AED 25,000 per month"), 300000)
        self.assertEqual(parse_salary_floor("$45/hr"), 45 * 2080)
        self.assertIsNone(parse_salary_floor(""))


if __name__ == "__main__":
    unittest.main()

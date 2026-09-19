import unittest

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


class TestContextualSectorPolicy(unittest.TestCase):
    def test_legal_self_id_alcohol_word_does_not_block_iherb_style_role(self):
        job = JobPosting(
            title="Growth Marketing Manager (MEA)", company="iHerb", location="Dubai",
            description=("Lead regional growth, paid media and ecommerce acquisition.\n"
                         "Voluntary Self-Identification of Disability\n"
                         "Disabilities include alcoholism and alcohol use disorder."),
        )
        result = check_job(job, {"sector_exclusions": ["alcohol"]})
        self.assertEqual(result.verdict, "pass")

    def test_actual_alcohol_business_still_blocks(self):
        job = JobPosting(title="Marketing Manager", company="Bottle Co",
                         description="We sell and distribute alcohol and spirits to retailers.")
        result = check_job(job, {"sector_exclusions": ["alcohol"]})
        self.assertEqual(result.verdict, "block")

    def test_fx_cross_border_payments_matches_configured_forex_exclusion(self):
        job = JobPosting(
            title="Growth & Marketing Manager", company="Verto",
            description="Our B2B fintech platform provides FX and cross-border payments with currency conversion.",
        )
        result = check_job(job, {"sector_exclusions": ["forex trading"]})
        self.assertEqual(result.verdict, "block")
        self.assertIn("business context", result.reasons[0])

    def test_restaurant_payments_tech_is_not_hospitality_employer(self):
        job = JobPosting(
            title="Senior Growth Marketing Manager", company="Qlub",
            description="Qlub is a restaurant payments technology platform serving hospitality customers.",
        )
        result = check_job(job, {"sector_exclusions": ["hospitality", "hotel"]})
        self.assertEqual(result.verdict, "pass")

    def test_hotel_employer_still_blocks_hospitality(self):
        job = JobPosting(title="Digital Marketing Manager", company="Rixos Resort",
                         description="Join our luxury hospitality team at this five-star hotel and resort.")
        result = check_job(job, {"sector_exclusions": ["hospitality"]})
        self.assertEqual(result.verdict, "block")

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

class TestSectorBoundaryRegressions(unittest.TestCase):
    def test_neutral_fx_budgeting_is_not_forex_business(self):
        job = JobPosting(title="Retail Marketing Manager", company="Neutral Retail",
                         description="Lead campaigns and account for FX and currency conversion in campaign budgets.")
        self.assertEqual(check_job(job, {"sector_exclusions": ["forex trading"]}).verdict, "pass")

    def test_hotel_technology_words_do_not_override_direct_hotel_identity(self):
        job = JobPosting(title="Marketing Manager", company="Grand Hotel",
                         description="Grand Hotel is a luxury hotel. We use a software platform for hospitality operations and guest services.")
        self.assertEqual(check_job(job, {"sector_exclusions": ["hotel", "hospitality"]}).verdict, "block")

    def test_inline_equal_opportunity_alcohol_copy_is_ignored(self):
        job = JobPosting(title="Growth Marketing Manager", company="Retail Co",
                         description="Lead paid media and ecommerce growth. We are an equal opportunity employer. Disability categories include alcoholism and alcohol use disorder.")
        self.assertEqual(check_job(job, {"sector_exclusions": ["alcohol"]}).verdict, "pass")

    def test_inline_voluntary_self_id_alcohol_copy_is_ignored(self):
        job = JobPosting(title="Growth Marketing Manager", company="Retail Co",
                         description="Own acquisition and analytics. Voluntary Self-Identification of Disability: alcoholism and alcohol use disorder.")
        self.assertEqual(check_job(job, {"sector_exclusions": ["alcohol"]}).verdict, "pass")

class TestForexProviderPhrasing(unittest.TestCase):
    def check(self, description, company="Acme"):
        job = JobPosting(title="Growth Marketing Manager", company=company, location="Dubai",
                         description=description)
        return check_job(job, {"sector_exclusions": ["forex trading"]}).verdict

    def test_provider_for_foreign_exchange_blocks(self):
        # Exact independent-review probe wording.
        self.assertEqual(self.check(
            "Verto is a fintech provider for foreign exchange and cross-border payment services.",
            company="Verto"), "block")

    def test_provider_of_foreign_exchange_blocks(self):
        self.assertEqual(self.check("We are a regulated provider of foreign exchange services."), "block")

    def test_platform_for_cross_border_payments_blocks(self):
        self.assertEqual(self.check(
            "Our product is a platform for cross-border payments and currency conversion."), "block")

    def test_business_of_currency_exchange_blocks(self):
        self.assertEqual(self.check(
            "The group operates in the business of currency exchange and remittances."), "block")

    def test_platform_for_cross_border_payments_only_blocks(self):
        self.assertEqual(self.check(
            "Acme is a platform for cross-border payments."), "block")

    def test_cross_border_payments_platform_only_blocks(self):
        self.assertEqual(self.check(
            "Acme is a cross-border payments platform."), "block")

    def test_platform_for_spaced_cross_border_payments_only_blocks(self):
        self.assertEqual(self.check(
            "Acme is a platform for cross border payments."), "block")

    def test_spaced_cross_border_payments_platform_only_blocks(self):
        self.assertEqual(self.check(
            "Acme is a cross border payments platform."), "block")

    def test_company_for_foreign_exchange_blocks(self):
        self.assertEqual(self.check(
            "A technology company for foreign exchange and global payments."), "block")

    def test_foreign_exchange_provider_reversed_order_blocks(self):
        self.assertEqual(self.check(
            "Verto, a foreign exchange provider, is hiring growth marketers.", company="Verto"), "block")

    def test_customer_using_currency_conversion_services_is_neutral(self):
        self.assertEqual(self.check(
            "Our agency serves a travel customer who uses currency conversion services."), "pass")

    def test_customer_using_cross_border_payment_services_is_neutral(self):
        self.assertEqual(self.check(
            "We serve e-commerce brands; one customer uses cross-border payment services for suppliers."), "pass")

    def test_customer_using_foreign_exchange_for_invoices_is_neutral(self):
        self.assertEqual(self.check(
            "We serve e-commerce brands; one customer uses foreign exchange for supplier invoices."), "pass")

    def test_fx_awareness_without_business_context_is_neutral(self):
        self.assertEqual(self.check(
            "The role requires awareness of FX risk in media buying."), "pass")

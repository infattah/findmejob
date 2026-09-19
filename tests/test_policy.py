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

class TestTrialFourSectorRegressions(unittest.TestCase):
    def check(self, title, company, description):
        return check_job(JobPosting(title=title, company=company, description=description),
                         {"sector_exclusions": ["forex trading", "hotel", "hospitality"]})

    def test_astra_remittance_role_blocks(self):
        result = self.check(
            "Growth Manager, Remittance", "Astra Tech",
            "Build the remittance growth engine and improve FX transfer transactions.")
        self.assertEqual(result.verdict, "block")

    def test_remittance_provider_business_blocks(self):
        result = self.check(
            "Growth Manager", "Transfer Co",
            "We are a digital provider of remittances and payment transactions.")
        self.assertEqual(result.verdict, "block")

    def test_neutral_payment_mentions_do_not_block(self):
        result = self.check(
            "Ecommerce Marketing Manager", "Retail Co",
            "Improve checkout conversion and measure customer payment transactions.")
        self.assertEqual(result.verdict, "pass")

    def test_generic_payment_role_title_is_neutral(self):
        result = self.check(
            "Payments Marketing Manager", "Retail Software Co",
            "Market checkout software to online merchants and analyze card payment conversion.")
        self.assertEqual(result.verdict, "pass")

    def test_payment_transaction_provider_business_blocks(self):
        result = self.check(
            "Growth Manager", "Transfer Network",
            "Our network provides regulated payment transactions for international transfers.")
        self.assertEqual(result.verdict, "block")

    def test_disability_accommodation_request_does_not_imply_hotel(self):
        result = self.check(
            "Principal Solution Engineer - Marketing Cloud", "Salesforce",
            "Salesforce is a cloud software company. Applicants needing an accommodation request because of a disability may contact recruiting.")
        self.assertEqual(result.verdict, "pass")

    def test_direct_hotel_identity_still_wins(self):
        result = self.check(
            "Software Marketing Manager", "Grand Hotel",
            "We operate a hotel and use cloud software. Accommodation requests due to disability are welcome.")
        self.assertEqual(result.verdict, "block")

class TestTrialFourIndependentReviewPaymentBoundaries(unittest.TestCase):
    policy = {"sector_exclusions": ["forex trading"]}

    def verdict(self, title, company, description):
        return check_job(JobPosting(title=title, company=company, description=description), self.policy).verdict

    def test_payment_transaction_analytics_provider_wording_is_neutral(self):
        self.assertEqual(self.verdict(
            "Analytics Manager", "Data Co",
            "We provide payment transaction analytics to online retailers."), "pass")

    def test_payment_transaction_reporting_and_measurement_are_neutral(self):
        for noun in ("reporting", "measurement", "metrics", "insights"):
            with self.subTest(noun=noun):
                self.assertEqual(self.verdict(
                    "Analytics Manager", "Data Co",
                    f"We provide payment transaction {noun} to online retailers."), "pass")

    def test_payment_transactions_product_title_at_retailer_is_neutral(self):
        self.assertEqual(self.verdict(
            "Payment Transactions Product Manager", "Retail Co",
            "Own checkout product workflows for online retail."), "pass")

    def test_payment_transactions_marketing_title_at_retailer_is_neutral(self):
        self.assertEqual(self.verdict(
            "Payment Transaction Marketing Manager", "Retail Co",
            "Market our ecommerce checkout experience."), "pass")

    def test_actual_payment_transaction_provider_still_blocks(self):
        self.assertEqual(self.verdict(
            "Product Manager", "Transfer Co",
            "We facilitate and process regulated payment transactions for merchants."), "block")

    def test_remittance_and_fx_providers_still_block(self):
        for description in (
            "We offer remittance services to consumers.",
            "Our platform facilitates foreign exchange for international businesses.",
        ):
            with self.subTest(description=description):
                self.assertEqual(self.verdict("Growth Manager", "Transfer Co", description), "block")

class TestTrialFourIndependentReviewPaymentBoundaries(unittest.TestCase):
    policy = {"sector_exclusions": ["forex trading"]}

    def verdict(self, title, company, description):
        return check_job(JobPosting(title=title, company=company, description=description), self.policy).verdict

    def test_payment_transaction_analytics_provider_wording_is_neutral(self):
        self.assertEqual(self.verdict("Analytics Manager", "Data Co", "We provide payment transaction analytics to online retailers."), "pass")

    def test_payment_transaction_reporting_and_measurement_are_neutral(self):
        for noun in ("reporting", "measurement", "metrics", "insights"):
            with self.subTest(noun=noun):
                self.assertEqual(self.verdict("Analytics Manager", "Data Co", f"We provide payment transaction {noun} to online retailers."), "pass")

    def test_payment_transactions_product_title_at_retailer_is_neutral(self):
        self.assertEqual(self.verdict("Payment Transactions Product Manager", "Retail Co", "Own checkout product workflows for online retail."), "pass")

    def test_payment_transactions_marketing_title_at_retailer_is_neutral(self):
        self.assertEqual(self.verdict("Payment Transaction Marketing Manager", "Retail Co", "Market our ecommerce checkout experience."), "pass")

    def test_actual_payment_transaction_provider_still_blocks(self):
        self.assertEqual(self.verdict("Product Manager", "Transfer Co", "We facilitate and process regulated payment transactions for merchants."), "block")

    def test_remittance_and_fx_providers_still_block(self):
        for description in ("We offer remittance services to consumers.", "Our platform facilitates foreign exchange for international businesses."):
            with self.subTest(description=description):
                self.assertEqual(self.verdict("Growth Manager", "Transfer Co", description), "block")


class TestFinalReviewPaymentAndHotelBoundaries(unittest.TestCase):
    forex = {"sector_exclusions": ["forex trading"]}

    def verdict(self, description, title="Role", company="Data Co", policy=None):
        job = JobPosting(title=title, company=company, description=description)
        return check_job(job, policy or self.forex).verdict

    def test_canonical_payment_processors_block(self):
        cases = (
            "We process payment transactions for merchants across the region.",
            "We are a payment processing company serving online merchants.",
            "Our platform processes regulated payment transactions.",
        )
        for description in cases:
            with self.subTest(description=description):
                self.assertEqual(self.verdict(description, company="Transfer Co"), "block")

    def test_neutral_transaction_analysis_both_word_orders(self):
        cases = (
            "We provide analytics for payment transactions to online retailers.",
            "We publish measurement of payment transactions for merchants.",
            "We deliver insights into payment transactions for retail teams.",
            "We provide reporting on payment transactions to online retailers.",
            "We measure customer payment transactions to improve checkout conversion.",
        )
        for description in cases:
            with self.subTest(description=description):
                self.assertEqual(self.verdict(description), "pass")

    def test_processing_mention_as_customer_activity_is_neutral(self):
        self.assertEqual(self.verdict(
            "Our analytics client processes payment transactions for its own customers."), "pass")

    def test_plural_hotel_business_blocks(self):
        policy = {"sector_exclusions": ["hotel", "hospitality"]}
        self.assertEqual(self.verdict(
            "We operate hotels and resorts across the Gulf.", company="Stay Group", policy=policy), "block")

    def test_software_for_plural_hotels_stays_neutral(self):
        policy = {"sector_exclusions": ["hotel", "hospitality"]}
        self.assertEqual(self.verdict(
            "Our SaaS platform serves hotels and hospitality operators.",
            company="Cloud Software Co", policy=policy), "pass")

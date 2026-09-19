import unittest

from findmejob.evidence import evaluate_requirements
from findmejob.models import Experience, JobPosting, Profile

# Exact staging trial 2 (2026-09-19) job-description wordings that produced
# false-negative hard-gap notes on clear strong roles.

CHAIN_REACTION_DESC = ("Award-winning GCC digital marketing agency. Manage and optimise Google Ads, "
                       "Meta and display campaigns; report CPL and prospect generation; manage budgets "
                       "and ROI. Requires 2+ years, Google Ads, Analytics, retargeting and A/B testing.")
DELIVEROO_DESC = ("Full-funnel campaigns across YouTube, Meta, Snapchat, TikTok and programmatic; "
                  "media planning, performance reporting, ROI and KPI analysis. Requires 3-5 years "
                  "and local media knowledge; agency experience good to have.")
ADAM_GLOBAL_DESC = ("On-site performance marketing role owning Google, Meta, LinkedIn and remarketing; "
                    "budget, CPL, CVR, ROAS, GA4, GTM, conversion tracking, dashboards, A/B testing "
                    "and sales alignment. Requires 3-5+ years.")
EASYGENERATOR_DESC = ("Own Google Ads and Microsoft Ads, Performance Max, AI-assisted optimisation, "
                      "CRM conversion tracking, landing-page CRO, A/B tests, budgets, CAC CPL ROAS "
                      "and dashboards. Requires 5+ years paid search and B2B SaaS/startup experience.")


def trial_profile():
    return Profile(
        summary=("Performance marketer and marketing automation builder with 7+ years of experience "
                 "across real estate, agency, e-commerce client reporting, education, paid acquisition, "
                 "analytics, CRM and automation. Hands-on with Meta Ads, Google Ads, TikTok, Snapchat, "
                 "LinkedIn Ads, GA4, GTM, Meta CAPI, offline conversion tracking and HubSpot."),
        skills=["Performance marketing and paid media", "Meta Ads and Google Ads",
                "GA4 and Google Tag Manager", "Conversion tracking, attribution and Meta CAPI",
                "Lead generation, CPL, CPA, ROAS and campaign optimisation",
                "Landing pages, funnel optimisation and A/B testing",
                "Reporting, dashboards and stakeholder communication",
                "Agency account and team leadership"],
        experiences=[Experience(role="Performance Marketing", company="Royal Palace Investment",
                                bullets=["Rebuilt real-estate paid acquisition and cut CPL 57%."]),
                     Experience(role="Marketing Manager", company="Almeka marketing agency",
                                bullets=["Led client performance marketing and agency delivery.",
                                         "Tracked e-commerce CVR, AOV and revenue in GA4 for about two years."])])


def evaluate(desc):
    return evaluate_requirements(trial_profile(), JobPosting(title="T", company="C", description=desc))


def by_text(report):
    return {item.requirement: item for item in report.items}


class TrialTwoCompoundRequirements(unittest.TestCase):

    def test_chain_reaction_compound_sentence_is_not_a_hard_gap(self):
        report = evaluate(CHAIN_REACTION_DESC)
        self.assertEqual(report.hard_missing, 0)
        items = by_text(report)
        self.assertEqual(items["Requires 2+ years"].status, "strong")
        self.assertIn("7+ years", items["Requires 2+ years"].evidence[0])
        self.assertEqual(items["Google Ads"].status, "strong")
        self.assertEqual(items["Analytics"].status, "strong")
        self.assertEqual(items["A/B testing"].status, "strong")
        # Honest soft gap: the CV shows no retargeting evidence, but it is
        # not a hard requirement and must not block the role.
        self.assertEqual(items["retargeting"].status, "missing")
        self.assertFalse(items["retargeting"].hard)

    def test_deliveroo_years_and_preferred_clause_decompose(self):
        report = evaluate(DELIVEROO_DESC)
        self.assertEqual(report.hard_missing, 0)
        items = by_text(report)
        self.assertEqual(items["Requires 3-5 years"].status, "strong")
        self.assertIn("7+ years", items["Requires 3-5 years"].evidence[0])
        self.assertFalse(items["local media knowledge"].hard)
        self.assertTrue(items["agency experience"].preferred)
        self.assertFalse(items["agency experience"].hard)
        self.assertEqual(items["agency experience"].status, "strong")

    def test_adam_global_standalone_years_match_explicit_cv_years(self):
        report = evaluate(ADAM_GLOBAL_DESC)
        self.assertEqual(report.hard_missing, 0)
        items = by_text(report)
        self.assertEqual(items["Requires 3-5+ years"].status, "strong")
        self.assertIn("7+ years", items["Requires 3-5+ years"].evidence[0])

    def test_known_strong_roles_remain_visible(self):
        # 100% recall guard: none of the three clear strong roles may be
        # pushed into a hard-gap state by decomposition.
        for desc in (CHAIN_REACTION_DESC, DELIVEROO_DESC, ADAM_GLOBAL_DESC):
            report = evaluate(desc)
            self.assertEqual(report.hard_missing, 0)
            self.assertGreaterEqual(report.strong, 1)

    def test_domain_bound_years_stay_strict(self):
        # The conditional trial 2 role keeps its hard gap: paid search and
        # B2B SaaS directly modify the years and are not CV-grounded.
        report = evaluate(EASYGENERATOR_DESC)
        self.assertEqual(report.hard_missing, 1)
        item = report.items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "missing")

    def test_independent_hard_clause_in_compound_stays_strict(self):
        job = JobPosting(title="T", company="C",
                         description="Requires 2+ years, Google Ads and Analytics. Fluent written Arabic is required.")
        report = evaluate_requirements(trial_profile(), job)
        self.assertEqual(report.hard_missing, 1)
        items = by_text(report)
        self.assertEqual(items["Requires 2+ years"].status, "strong")
        self.assertEqual(items["Fluent written Arabic is required"].status, "missing")
        self.assertTrue(items["Fluent written Arabic is required"].hard)

    def test_preferred_clause_can_never_be_hard(self):
        # "preferred" bullets are section-header words, so use "good to have".
        job = JobPosting(title="T", company="C",
                         description="Requirements\n- Requires 3+ years of experience. B2B SaaS experience good to have")
        report = evaluate_requirements(trial_profile(), job)
        self.assertEqual(report.hard_missing, 0)
        items = by_text(report)
        self.assertEqual(items["Requires 3+ years of experience"].status, "strong")
        self.assertTrue(items["B2B SaaS experience"].preferred)
        self.assertFalse(items["B2B SaaS experience"].hard)
        self.assertEqual(items["B2B SaaS experience"].status, "missing")

    def test_generic_years_stay_bound_to_adjacent_requirement_sentence(self):
        # Decomposition must not detach "5+ years of experience" from the
        # B2B SaaS requirement sentence it belongs to.
        profile = Profile(summary="9+ years in consumer retail")
        job = JobPosting(title="Lead", company="Acme",
                         description="Requirements\n- 5+ years of experience. B2B SaaS demand generation expertise required")
        item = evaluate_requirements(profile, job).items[0]
        self.assertTrue(item.hard)
        self.assertEqual(item.status, "missing")


if __name__ == "__main__":
    unittest.main()

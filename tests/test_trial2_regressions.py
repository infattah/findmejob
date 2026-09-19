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


WEAK_PROFILE = Profile(summary="Retail sales assistant with 1 year of shop floor experience.")


def weak_evaluate(desc, **kwargs):
    return evaluate_requirements(WEAK_PROFILE, JobPosting(title="T", company="C", description=desc), **kwargs)


class TrialTwoReviewStrictness(unittest.TestCase):
    """Blocking strictness holes from the independent PR 4 review (2026-09-20)."""

    def test_comma_preferred_tail_never_softens_hard_years(self):
        # Reviewer probe: "Requires 5+ years, Google Ads, MBA good to have."
        # downgraded the hard years clause to preferred on the reviewed head.
        report = weak_evaluate("Requires 5+ years, Google Ads, MBA good to have.")
        self.assertEqual(report.hard_missing, 1)
        items = by_text(report)
        self.assertEqual(items["Requires 5+ years"].status, "missing")
        self.assertTrue(items["Requires 5+ years"].hard)
        self.assertFalse(items["Requires 5+ years"].preferred)
        self.assertIn("MBA", items)  # preferred marker stripped from the text
        self.assertTrue(items["MBA"].preferred)
        self.assertFalse(items["MBA"].hard)

    def test_comma_preferred_tail_keeps_hard_years_on_strong_cv(self):
        report = evaluate("Requires 5+ years, Google Ads, MBA good to have.")
        self.assertEqual(report.hard_missing, 0)
        items = by_text(report)
        self.assertEqual(items["Requires 5+ years"].status, "strong")
        self.assertTrue(items["Requires 5+ years"].hard)
        self.assertFalse(items["Requires 5+ years"].preferred)
        self.assertTrue(items["MBA"].preferred)

    def test_comma_preferred_tail_never_softens_hard_skill_clause(self):
        # Same defect class without a years clause: a hard comma clause must
        # survive a "good to have" tail in its own sentence.
        report = weak_evaluate("B2B SaaS experience required, MBA good to have.")
        self.assertEqual(report.hard_missing, 1)
        items = by_text(report)
        self.assertTrue(items["B2B SaaS experience required"].hard)
        self.assertFalse(items["B2B SaaS experience required"].preferred)
        self.assertTrue(items["MBA"].preferred)

    def test_long_decomposition_never_drops_trailing_hard_requirement(self):
        # Reviewer probe: 6 comma-list requirements (30+ decomposed clauses)
        # pushed a trailing hard requirement past the old max_items cap.
        lines = ["Requirements"]
        for i in range(6):
            lines.append(f"- Requires {i + 2}+ years, Skillalpha{i}, Skillbeta{i}, "
                         f"Skillgamma{i}, Skilldelta{i} good to have.")
        lines.append("- Fluent written Arabic is required.")
        desc = "\n".join(lines)
        report = weak_evaluate(desc)
        items = by_text(report)
        self.assertIn("Fluent written Arabic is required", items)
        self.assertTrue(items["Fluent written Arabic is required"].hard)
        self.assertEqual(items["Fluent written Arabic is required"].status, "missing")
        self.assertGreaterEqual(report.hard_missing, 7)  # 6 year gates + Arabic

    def test_reporting_cap_still_covers_hard_gaps_and_every_requirement(self):
        # Even under a deliberately tight cap, hard clauses are evaluated and
        # every extracted requirement keeps at least one evaluated item.
        lines = ["Requirements"]
        for i in range(6):
            lines.append(f"- Requires {i + 2}+ years, Skillalpha{i}, Skillbeta{i}, "
                         f"Skillgamma{i}, Skilldelta{i} good to have.")
        lines.append("- Fluent written Arabic is required.")
        report = weak_evaluate("\n".join(lines), max_items=8)
        items = by_text(report)
        for i in range(6):
            self.assertIn(f"Requires {i + 2}+ years", items)
        self.assertIn("Fluent written Arabic is required", items)
        self.assertTrue(items["Fluent written Arabic is required"].hard)
        self.assertGreaterEqual(report.hard_missing, 7)

    def test_more_than_200_hard_atoms_never_drop_trailing_hard_requirement(self):
        # Independent final-review boundary probe: ten valid source lines each
        # decompose into one hard years gate plus twenty hard skill atoms. The
        # old absolute 200-item early return stopped during line ten and hid
        # the trailing fluent-Arabic hard requirement.
        lines = ["Requirements"]
        for line_no in range(10):
            atoms = ", ".join(f"must S{line_no:02d}{atom_no:02d}" for atom_no in range(20))
            line = f"- Requires {line_no + 2}+ years, {atoms}."
            self.assertLessEqual(len(line.removeprefix("- ")), 300)
            lines.append(line)
        lines.append("- Fluent written Arabic is required.")
        report = weak_evaluate("\n".join(lines), max_items=8)
        items = by_text(report)
        self.assertGreater(len(report.items), 200)
        self.assertIn("Fluent written Arabic is required", items)
        arabic = items["Fluent written Arabic is required"]
        self.assertTrue(arabic.hard)
        self.assertEqual(arabic.status, "missing")
        # Every one of the 210 preceding hard clauses is evaluated too.
        self.assertEqual(report.hard_missing, 211)

    def test_low_soft_cap_bounds_detail_without_hiding_source_or_hard_items(self):
        desc = ("Requirements\n"
                "- Collaboration skills, communication skills, presentation skills.\n"
                "- Requires 5+ years, Google Ads, MBA good to have.\n"
                "- Fluent written Arabic is required.")
        report = weak_evaluate(desc, max_items=1)
        items = by_text(report)
        # One representative survives for the soft-only source requirement;
        # hard clauses from later sources remain visible beyond the soft cap.
        self.assertIn("Collaboration skills, communication skills, presentation skills", items)
        self.assertIn("Requires 5+ years", items)
        self.assertIn("Fluent written Arabic is required", items)
        self.assertTrue(items["Requires 5+ years"].hard)
        self.assertTrue(items["Fluent written Arabic is required"].hard)

    def test_ordinary_workload_stays_compact(self):
        report = evaluate(CHAIN_REACTION_DESC)
        self.assertLessEqual(len(report.items), 8)
        self.assertEqual(report.hard_missing, 0)

    def test_numeric_threshold_years_stay_distinct(self):
        # Reviewer note: bare generic year heads with different thresholds
        # deduped into one item because the key ignored digits.
        report = evaluate("Requires 2+ years, Google Ads. Requires 5+ years, Meta Ads.")
        items = by_text(report)
        self.assertIn("Requires 2+ years", items)
        self.assertIn("Requires 5+ years", items)
        self.assertEqual(items["Requires 2+ years"].status, "strong")
        self.assertEqual(items["Requires 5+ years"].status, "strong")


if __name__ == "__main__":
    unittest.main()

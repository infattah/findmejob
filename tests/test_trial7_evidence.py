import unittest
from findmejob.evidence import evaluate_requirements
from findmejob.models import JobPosting,Profile,Experience

class TrialSevenDeliverooRegressions(unittest.TestCase):
    def profile(self):
        return Profile(summary="Performance marketer with 7+ years in marketing overall. English: fluent professional working proficiency.",skills=["Growth and performance marketing","Promotions, paid acquisition and campaign analytics","Brand building and campaign project management"],experiences=[Experience(role="Marketing Manager",company="Almeka agency",bullets=["Built an education brand end to end and led the campaign team.","Led promotion campaigns and performance reporting."])])
    def test_growth_marketing_range_combines_total_tenure_with_grounded_work(self):
        job=JobPosting(title="Marketing Manager, Promotions",company="Deliveroo",description="Responsibilities\nOwn promotional campaigns, CAC and performance analytics.\nRequirements\n- 5-8 years of experience in Growth Marketing")
        item=evaluate_requirements(self.profile(),job).items[0]
        self.assertEqual("strong",item.status)
    def test_brand_campaign_range_combines_total_tenure_with_agency_evidence(self):
        job=JobPosting(title="Marketing Manager, Brand",company="Deliveroo",description="Responsibilities\nOwn integrated brand campaigns and project delivery.\nRequirements\n- Minimum 6-8 years of experience in brand marketing, campaign and project management")
        item=evaluate_requirements(self.profile(),job).items[0]
        self.assertEqual("strong",item.status)
    def test_unrelated_tenure_cannot_transfer_to_growth(self):
        p=Profile(summary="Software engineer with 9+ years in software engineering.",skills=["Python"])
        job=JobPosting(title="Growth Manager",company="Acme",description="Requirements\n- 5-8 years in Growth Marketing")
        self.assertNotEqual("strong",evaluate_requirements(p,job).items[0].status)
    def test_generic_marketing_without_growth_evidence_is_not_enough(self):
        p=Profile(summary="Marketer with 7+ years in corporate communications.")
        job=JobPosting(title="Growth Manager",company="Acme",description="Requirements\n- 5-8 years in Growth Marketing")
        self.assertNotEqual("strong",evaluate_requirements(p,job).items[0].status)

class ExplicitLanguageEvidenceTests(unittest.TestCase):
    def item(self,summary,req):
        return evaluate_requirements(Profile(summary=summary),JobPosting(title="T",company="C",description="Requirements\n- "+req)).items[0]
    def test_explicit_fluent_english_grounds_requirement(self):
        self.assertEqual("strong",self.item("Languages: English - fluent professional working proficiency.","Fluent English").status)
    def test_english_cv_alone_does_not_ground_fluency(self):
        self.assertEqual("missing",self.item("Experienced marketer writing a detailed CV in English.","Fluent English").status)
    def test_working_proficiency_can_ground_fluent_for_work(self):
        self.assertEqual("strong",self.item("English: professional working proficiency.","Fluent English").status)
    def test_fluent_does_not_invent_native_or_bilingual(self):
        self.assertEqual("missing",self.item("English: fluent professional working proficiency.","Native English").status)
    def test_wrong_language_does_not_transfer(self):
        self.assertEqual("missing",self.item("Arabic: fluent.","Fluent English").status)

if __name__=='__main__': unittest.main()

class ReviewerContextualEvidenceNegatives(unittest.TestCase):
    def match(self,summary,req):
        return evaluate_requirements(Profile(summary=summary),JobPosting(title="T",company="C",description="Requirements\n- "+req))
    def test_growth_marketing_false_friends(self):
        req="5-8 years in Growth Marketing"
        for text in ("7+ years in marketing. Media relations and press releases.","7+ years in marketing. Retail sales promotions.","7+ years in marketing. Growth mindset."):
            with self.subTest(text=text): self.assertNotEqual("strong",self.match(text,req).items[0].status)
    def test_brand_campaign_false_friends(self):
        req="6-8 years in brand marketing, campaign and project management"
        for text in ("7+ years in marketing. Software project management.","7+ years in marketing. One charity campaign."):
            with self.subTest(text=text): self.assertNotEqual("strong",self.match(text,req).items[0].status)
    def test_mixed_hard_clause_preserves_missing_tenure(self):
        report=self.match("English: fluent professional working proficiency. 2 years in growth marketing.","Fluent English and 5 years of growth marketing")
        self.assertGreaterEqual(report.hard_missing,1)
        self.assertTrue(any("5 years" in i.requirement and i.status!="strong" for i in report.items))

class LanguageModalityTests(unittest.TestCase):
    def status(self,summary,req):
        return evaluate_requirements(Profile(summary=summary),JobPosting(title="T",company="C",description="Requirements\n- "+req)).items[0].status
    def test_spoken_does_not_satisfy_written(self): self.assertEqual("missing",self.status("English: spoken fluent.","Written fluent English"))
    def test_written_does_not_satisfy_spoken(self): self.assertEqual("missing",self.status("English: written fluent.","Spoken fluent English"))
    def test_general_explicit_proficiency_covers_both(self):
        self.assertEqual("strong", self.status("English: fluent professional proficiency.", "Written fluent English"))
        self.assertEqual("strong", self.status("English: fluent professional proficiency.", "Spoken fluent English"))

    def test_one_modality_does_not_satisfy_general(self):
        self.assertEqual("missing", self.status("English: spoken fluent.", "Fluent English"))

    def test_both_modalities_satisfy_general_and_both(self):
        evidence = "English: written and spoken fluent."
        self.assertEqual("strong", self.status(evidence, "Fluent English"))
        self.assertEqual("strong", self.status(evidence, "Fluent in written and spoken English"))

class MixedHardSeparatorRegressions(unittest.TestCase):
    def report(self, req):
        profile = Profile(summary="English: fluent professional proficiency. 2 years in growth marketing.")
        return evaluate_requirements(profile, JobPosting(title="T", company="C", description="Requirements\n- " + req))

    def test_all_separator_and_order_variants_preserve_both_constraints(self):
        variants = (
            "Fluent English / 5 years of growth marketing",
            "5 years of growth marketing / Fluent English",
            "Fluent English & 5 years of growth marketing",
            "5 years of growth marketing & Fluent English",
            "Fluent English plus 5 years of growth marketing.",
            "5 years of growth marketing, plus Fluent English",
            "Fluent English as well as 5 years of growth marketing;",
            "5 years of growth marketing; as well as Fluent English",
        )
        for req in variants:
            with self.subTest(req=req):
                report = self.report(req)
                self.assertTrue(any("5 years" in item.requirement and item.status != "strong" for item in report.items))
                self.assertGreaterEqual(report.hard_missing, 1)

    def test_unknown_conjunction_keeps_compound_unresolved(self):
        report = self.report("Fluent English alongside 5 years of growth marketing")
        self.assertEqual(0, report.strong)
        self.assertGreaterEqual(report.hard_missing, 1)


class MultiLanguageBindingRegressions(unittest.TestCase):
    def status(self, evidence, requirement):
        return evaluate_requirements(
            Profile(summary=evidence),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        ).items[0].status

    def test_level_stays_bound_to_same_language(self):
        variants = (
            ("English fluent and Arabic native", "Native English"),
            ("Arabic native; English fluent.", "Native English"),
            ("English basic and Arabic fluent", "Fluent English"),
            ("Arabic fluent / English basic", "Fluent English"),
        )
        for evidence, requirement in variants:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence, requirement))

    def test_modality_stays_bound_to_same_language(self):
        variants = (
            ("English spoken fluent; Arabic written fluent", "Written fluent English"),
            ("Arabic written fluent, English spoken fluent", "Written fluent English"),
            ("English written fluent / Arabic spoken fluent", "Spoken fluent English"),
            ("Arabic spoken fluent and English written fluent", "Spoken fluent English"),
            ("English spoken fluent; Arabic fluent professional proficiency", "Fluent English"),
        )
        for evidence, requirement in variants:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence, requirement))

    def test_general_same_language_evidence_covers_modalities(self):
        evidence = "Arabic native; English fluent professional proficiency."
        self.assertEqual("strong", self.status(evidence, "Written fluent English"))
        self.assertEqual("strong", self.status(evidence, "Spoken fluent English"))

class ConnectorAgnosticResidualRegressions(unittest.TestCase):
    joins = ("with", "alongside", "together with", "combined with", "-", ":", "—")

    def report(self, summary, requirement):
        return evaluate_requirements(
            Profile(summary=summary),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        )

    def test_language_residual_blocks_years_strong_in_both_orders(self):
        summary = "7+ years in growth marketing. English: fluent professional proficiency."
        for join in self.joins:
            for requirement in (
                f"5 years of growth marketing {join} fluent English",
                f"fluent English {join} 5 years of growth marketing",
            ):
                with self.subTest(requirement=requirement):
                    report = self.report(summary, requirement)
                    self.assertEqual(0, report.strong)
                    self.assertGreaterEqual(report.hard_missing, 1)

    def test_nonlanguage_residual_blocks_years_strong_in_both_orders(self):
        summary = "7+ years in growth marketing. B2B SaaS experience."
        for join in self.joins:
            for requirement in (
                f"5 years of growth marketing {join} B2B SaaS experience",
                f"B2B SaaS experience {join} 5 years of growth marketing",
            ):
                with self.subTest(requirement=requirement):
                    report = self.report(summary, requirement)
                    self.assertEqual(0, report.strong)
                    self.assertGreaterEqual(report.hard_missing, 1)


class CapitalizedModalityRegressions(unittest.TestCase):
    def status(self, summary, requirement):
        return evaluate_requirements(
            Profile(summary=summary),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        ).items[0].status

    def test_capitalized_written_matches_equivalent_evidence(self):
        self.assertEqual("strong", self.status("English: Written fluent.", "Written fluent English"))

    def test_capitalized_modalities_still_do_not_cross(self):
        self.assertEqual("missing", self.status("English: Spoken fluent.", "Written fluent English"))
        self.assertEqual("missing", self.status("English: Written fluent.", "Spoken fluent English"))

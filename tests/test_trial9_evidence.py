import unittest
from findmejob.evidence import evaluate_requirements
from findmejob.models import JobPosting, Profile


class CompoundEvidenceCompositionTests(unittest.TestCase):
    requirement = "Hands-on proficiency with HubSpot and product analytics tools"

    def status(self, skills, requirement=None):
        report = evaluate_requirements(
            Profile(skills=skills),
            JobPosting(title="T", company="C", description="Requirements\n- " + (requirement or self.requirement)),
        )
        return report.items[0].status

    def test_verto_positive_combines_explicit_required_components(self):
        self.assertEqual("strong", self.status(["HubSpot", "Product analytics tools: PostHog and GA4"]))

    def test_only_hubspot_is_missing(self):
        self.assertEqual("missing", self.status(["HubSpot"]))

    def test_only_generic_analytics_is_missing(self):
        self.assertEqual("missing", self.status(["Analytics and reporting"]))

    def test_unrelated_analytics_is_missing(self):
        self.assertEqual("missing", self.status(["HubSpot", "Financial analytics in Excel"]))

    def test_vague_tool_use_is_missing(self):
        self.assertEqual("missing", self.status(["HubSpot", "Used many tools proficiently"]))

    def test_or_does_not_require_or_compose_both_branches(self):
        self.assertEqual("strong", self.status(["HubSpot"], "Proficiency with HubSpot or Salesforce"))
        self.assertEqual("missing", self.status(["Marketing tools"], "Proficiency with HubSpot or Salesforce"))

    def test_optional_component_does_not_become_required(self):
        self.assertEqual("strong", self.status(["HubSpot"], "Proficiency with HubSpot; product analytics tools preferred"))

    def test_proficiency_level_mismatch_is_missing(self):
        self.assertEqual("missing", self.status(["Basic exposure to HubSpot", "Product analytics tools: PostHog"]))

    def test_one_required_component_absent_is_missing(self):
        self.assertEqual("missing", self.status(["Product analytics tools: PostHog and GA4"]))

    def test_weak_fragments_do_not_combine(self):
        self.assertEqual("missing", self.status(["Some HubSpot exposure", "Interested in analytics tools"]))

class CompoundSafetyReviewTests(unittest.TestCase):
    def report(self, skills, requirement):
        return evaluate_requirements(
            Profile(skills=skills),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        )

    def test_numeric_tenure_never_uses_compound_composition(self):
        cases = (
            "5+ years of expertise in Python and SQL",
            "Expertise in Python and SQL - 5+ years",
            "Python and SQL expertise: 5+ years",
            "5+ years: expertise in Python & SQL",
        )
        for requirement in cases:
            with self.subTest(requirement=requirement):
                self.assertNotEqual("strong", self.report(["Python", "SQL"], requirement).items[0].status)

    def test_mixed_hubspot_and_tenure_cannot_compose(self):
        cases = (
            "Hands-on proficiency with HubSpot and 5+ years in B2B SaaS marketing",
            "5+ years in B2B SaaS marketing and hands-on proficiency with HubSpot",
            "Hands-on proficiency with HubSpot; 5+ years in B2B SaaS marketing",
            "5+ years in B2B SaaS marketing - hands-on proficiency with HubSpot",
        )
        skills = ["HubSpot", "B2B SaaS marketing"]
        for requirement in cases:
            with self.subTest(requirement=requirement):
                report = self.report(skills, requirement)
                self.assertGreaterEqual(report.hard_missing, 1)

    def test_low_confidence_cues_do_not_satisfy_proficiency(self):
        for weak in (
            "Familiarity with HubSpot",
            "Familiar with HubSpot",
            "Working knowledge of HubSpot",
            "Awareness of HubSpot",
            "Introductory HubSpot knowledge",
        ):
            with self.subTest(weak=weak):
                report = self.report([weak, "Product analytics tools: PostHog"], "Hands-on proficiency with HubSpot and product analytics tools")
                self.assertEqual("missing", report.items[0].status)

    def test_negated_component_evidence_is_not_evidence(self):
        for negated in (
            "No experience with HubSpot",
            "not proficient in HubSpot",
            "without HubSpot experience",
        ):
            with self.subTest(negated=negated):
                report = self.report([negated, "Product analytics tools: PostHog"], "Hands-on proficiency with HubSpot and product analytics tools")
                self.assertEqual("missing", report.items[0].status)

    def test_negated_ordinary_evidence_is_not_evidence(self):
        for negated in (
            "No experience with HubSpot",
            "not proficient in HubSpot",
            "without HubSpot experience",
        ):
            with self.subTest(negated=negated):
                report = self.report([negated], "HubSpot experience required")
                self.assertEqual("missing", report.items[0].status)

class StructuralEvidenceStrengthTests(unittest.TestCase):
    requirement = "Hands-on proficiency with HubSpot and product analytics tools"

    def status(self, skills, requirement=None):
        return evaluate_requirements(
            Profile(skills=skills),
            JobPosting(title="T", company="C", description="Requirements\n- " + (requirement or self.requirement)),
        ).items[0].status

    def test_low_confidence_variants_are_not_strong(self):
        variants = (
            "Limited HubSpot use", "Novice HubSpot user", "Beginner in HubSpot",
            "Dabbled in HubSpot", "High-level understanding of HubSpot",
            "Occasional use of HubSpot", "Used HubSpot occasionally",
            "Familiarity with HubSpot", "Familiar with HubSpot",
            "Working knowledge of HubSpot",
        )
        for evidence in variants:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status([evidence, "Product analytics tools: PostHog"]))

    def test_normalized_negation_variants_are_not_evidence(self):
        variants = (
            "Lacks HubSpot experience", "Lack of HubSpot experience", "Never used HubSpot",
            "Never worked with HubSpot", "Not experienced with HubSpot", "Doesn't know HubSpot",
            "Don’t know HubSpot", "Haven't used HubSpot", "Have not used HubSpot", "No, HubSpot experience",
        )
        for evidence in variants:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status([evidence, "Product analytics tools: PostHog"]))

    def test_unrelated_negation_does_not_suppress_separate_positive_fragment(self):
        self.assertEqual("strong", self.status([
            "No Salesforce experience", "HubSpot", "Product analytics tools: PostHog"
        ]))

    def test_spelled_and_digit_tenure_compounds_fail_closed(self):
        variants = (
            "5+ years of expertise in Python and SQL",
            "five years of expertise in Python and SQL",
            "five or more years of expertise in Python and SQL",
            "at least five years of expertise in Python and SQL",
            "between five and seven years of expertise in Python and SQL",
        )
        for requirement in variants:
            with self.subTest(requirement=requirement):
                self.assertNotEqual("strong", self.status(["Python", "SQL"], requirement))

    def test_person_team_false_friends_do_not_prove_tenure(self):
        for evidence in ("Led a five person team", "Managed a 5-person team"):
            with self.subTest(evidence=evidence):
                self.assertNotEqual("strong", self.status([evidence, "Python", "SQL"], "five years of expertise in Python and SQL"))

    def test_ampersand_and_slash_are_mandatory_verto_compounds(self):
        for join in ("&", "/"):
            requirement = f"Hands-on proficiency with HubSpot {join} product analytics tools"
            with self.subTest(join=join):
                self.assertEqual("strong", self.status(["HubSpot", "Product analytics tools: PostHog"], requirement))
                self.assertEqual("missing", self.status(["HubSpot"], requirement))
                self.assertEqual("missing", self.status(["Product analytics tools: PostHog"], requirement))

class WeakEvidenceMorphologyTests(unittest.TestCase):
    requirement = "Hands-on proficiency with HubSpot and product analytics tools"

    def status(self, evidence):
        return evaluate_requirements(
            Profile(skills=[evidence, "Product analytics tools: PostHog"]),
            JobPosting(title="T", company="C", description="Requirements\n- " + self.requirement),
        ).items[0].status

    def test_frequency_and_low_level_forms_fail_closed(self):
        cases = (
            "Occasional HubSpot use", "HUBSPOT - occasionally used",
            "Sometimes used HubSpot", "HubSpot: rarely used", "Seldom using HubSpot",
            "High-level HubSpot knowledge", "HubSpot knowledge, high level",
            "Minimal HubSpot experience", "HubSpot experience: light",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

    def test_training_and_exploratory_forms_fail_closed(self):
        cases = (
            "Studied HubSpot in a course", "HubSpot coursework", "Attended HubSpot training",
            "Training attended: HUBSPOT", "Explored HubSpot", "HubSpot - exploring",
            "Played with HubSpot", "HubSpot, played with", "Shadowed HubSpot administration",
            "HubSpot administrators shadowed", "Attended certified HubSpot training",
            "HubSpot certification coursework",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

    def test_explicit_strong_forms_remain_strong(self):
        cases = (
            "HubSpot certified", "Certified HubSpot administrator", "HubSpot Administrator",
            "HubSpot power user", "Daily hands-on use of HubSpot",
            "Advanced proficiency in HubSpot",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("strong", self.status(evidence))

    def test_unrelated_weak_claim_does_not_suppress_target(self):
        self.assertEqual("strong", self.status("Rarely used Salesforce; HubSpot administrator"))
        self.assertEqual("strong", self.status("Minimal Salesforce experience. HubSpot power user"))

class WeakFrequencyClosureTests(unittest.TestCase):
    def status(self, evidence, skill="HubSpot"):
        requirement = f"Hands-on proficiency with {skill} and product analytics tools"
        return evaluate_requirements(
            Profile(skills=[evidence, "Product analytics tools: PostHog"]),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        ).items[0].status

    def test_frequency_is_weak_independent_of_activity_word(self):
        cases = (
            "Seldom worked with HubSpot", "Occasionally worked with HubSpot",
            "Rarely works with HubSpot", "Sometimes works on HubSpot",
            "Rarely touched HubSpot", "Occasional HubSpot administration",
            "HUBSPOT - SELDOM handled", "HubSpot, occasionally operated",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

    def test_frequency_is_profession_neutral(self):
        cases = (
            ("Rarely worked with Kubernetes", "Kubernetes"),
            ("Occasional Kubernetes administration", "Kubernetes"),
            ("Sometimes handled Terraform", "Terraform"),
            ("TERRAFORM: seldom operated", "Terraform"),
        )
        for evidence, skill in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence, skill))

    def test_none_is_negated_non_evidence(self):
        cases = (
            "HubSpot experience: none", "NONE - HubSpot experience",
            "HubSpot, none", "Experience with HubSpot? None.",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

    def test_unrelated_frequency_and_none_preserve_clause_locality(self):
        self.assertEqual("strong", self.status("Salesforce experience: none; HubSpot administrator"))
        self.assertEqual("strong", self.status("Rarely used Salesforce. HubSpot power user"))

class IndependentTargetClaimClosureTests(unittest.TestCase):
    def status(self, evidence, skill="HubSpot"):
        requirement = f"Hands-on proficiency with {skill} and product analytics tools"
        return evaluate_requirements(
            Profile(skills=[evidence, "Product analytics tools: PostHog"]),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        ).items[0].status

    def test_adjacent_anchorless_shorthand_remains_target_bound_and_weak(self):
        cases = (
            ("HubSpot; occasionally administered", "HubSpot"),
            ("HubSpot. Rarely handled", "HubSpot"),
            ("Kubernetes: occasionally operated", "Kubernetes"),
            ("Terraform; seldom worked with", "Terraform"),
            ("TERRAFORM? Sometimes administered", "Terraform"),
        )
        for evidence, skill in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence, skill))

    def test_separate_strong_target_claim_survives_discarded_non_evidence(self):
        cases = (
            "HubSpot experience: none; HubSpot administrator",
            "Experience with HubSpot? None. HubSpot administrator",
            "Rarely handled HubSpot; HubSpot power user",
            "HubSpot administrator. HubSpot experience: none",
            "HubSpot power user; occasionally handled HubSpot",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("strong", self.status(evidence))

    def test_only_weak_or_negated_target_claims_remain_missing(self):
        cases = (
            "HubSpot experience: none; rarely handled HubSpot",
            "HubSpot; occasionally administered",
            "Never used HubSpot. HubSpot coursework",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

class DefinitiveLocalityTests(unittest.TestCase):
    def status(self, evidence, skill="HubSpot"):
        requirement = f"Hands-on proficiency with {skill} and product analytics tools"
        return evaluate_requirements(
            Profile(skills=[evidence, "Product analytics tools: PostHog"]),
            JobPosting(title="T", company="C", description="Requirements\n- " + requirement),
        ).items[0].status

    def test_adjacent_different_target_never_inherits(self):
        cases = (
            "HubSpot administrator. Occasionally used Salesforce",
            "HubSpot administrator; Salesforce: rarely used",
            "HubSpot administrator. Never used Salesforce",
            "HubSpot administrator; Salesforce experience: none",
            "Salesforce rarely used; HubSpot administrator",
            "Never used Terraform. HubSpot power user",
            "HubSpot power user; Kubernetes occasionally operated",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("strong", self.status(evidence))

    def test_cross_target_claims_are_classified_only_for_their_target(self):
        evidence = "HubSpot administrator; Salesforce: rarely used"
        self.assertEqual("strong", self.status(evidence, "HubSpot"))
        self.assertEqual("missing", self.status(evidence, "Salesforce"))
        evidence = "Terraform experience: none. Kubernetes administrator"
        self.assertEqual("missing", self.status(evidence, "Terraform"))
        self.assertEqual("strong", self.status(evidence, "Kubernetes"))

    def test_contrast_coordinators_split_same_target_claims(self):
        cases = (
            "Rarely handled HubSpot, but HubSpot power user",
            "HubSpot power user, though HubSpot was rarely handled",
            "HUBSPOT rarely handled; HOWEVER, HubSpot administrator",
            "Although HubSpot was seldom used, HubSpot power user",
            "HubSpot administrator yet HubSpot experience: none",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("strong", self.status(evidence))

    def test_contrast_only_weak_same_target_remains_missing(self):
        cases = (
            "Rarely handled HubSpot, but sometimes used HubSpot",
            "HubSpot experience: none; however HubSpot was occasionally handled",
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.assertEqual("missing", self.status(evidence))

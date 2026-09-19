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

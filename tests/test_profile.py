import unittest
from pathlib import Path

from findmejob.profile import parse_master_cv

SAMPLE = Path(__file__).parent.parent / "sample_data" / "master_cv.example.md"


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.profile = parse_master_cv(SAMPLE.read_text())

    def test_identity(self):
        self.assertEqual(self.profile.full_name, "Alex Example")
        self.assertEqual(self.profile.email, "alex@example.com")

    def test_skills_and_experience(self):
        self.assertEqual(len(self.profile.skills), 8)
        self.assertEqual(len(self.profile.experiences), 2)
        exp = self.profile.experiences[0]
        self.assertEqual(exp.role, "Growth Marketing Lead")
        self.assertEqual(exp.company, "Northwind Goods")
        self.assertEqual(exp.start, "2021")
        self.assertEqual(exp.end, "Present")
        self.assertEqual(len(exp.bullets), 4)

    def test_links(self):
        self.assertIn("linkedin", self.profile.links)
        self.assertIn("github", self.profile.links)


if __name__ == "__main__":
    unittest.main()

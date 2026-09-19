import re
import tempfile
import unittest
from pathlib import Path

from findmejob.models import Education, Experience, JobPosting, Profile
from findmejob.render.pdf import render_cv_pdf


def profile(bullets_per_role=3, roles=2):
    return Profile(
        full_name="Alex Example", email="alex@example.com", phone="+1 555 0100",
        summary="Performance marketer.",
        skills=["Google Ads", "Meta Ads", "SEO"],
        experiences=[Experience(
            role=f"Role {i}", company=f"Company {i}", start="2020", end="2021",
            bullets=[f"Achievement number {j} with a long description that must wrap "
                     f"cleanly across at least two rendered lines in the PDF" * 2
                     for j in range(bullets_per_role)]) for i in range(roles)],
        education=[Education(degree="BBA", school="Example University", year="2018")])


class TestPdf(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.job = JobPosting(title="PMM", company="X", description="ads")

    def test_valid_structure(self):
        out = render_cv_pdf(profile(), self.job, self.dir / "cv.pdf")
        data = out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Type /Catalog", data)
        self.assertIn(b"startxref", data)
        # xref offsets must point at object headers
        for m in re.finditer(rb"(\d{10}) 00000 n", data):
            off = int(m.group(1))
            self.assertRegex(data[off:off + 20], rb"^\d+ 0 obj")

    def test_contains_cv_text(self):
        out = render_cv_pdf(profile(), self.job, self.dir / "cv.pdf")
        data = out.read_bytes()
        self.assertIn(b"Alex Example", data)
        self.assertIn(b"alex@example.com", data)
        self.assertIn(b"Experience", data)
        self.assertIn(b"Achievement number 1", data)

    def test_long_cv_paginates(self):
        out = render_cv_pdf(profile(bullets_per_role=40, roles=3), self.job, self.dir / "cv.pdf")
        data = out.read_bytes()
        page_count = len(re.findall(rb"/Type /Page[^s]", data))
        self.assertGreaterEqual(page_count, 2)

    def test_non_latin1_chars_do_not_break(self):
        p = profile()
        p.summary = "Fluent in Arabic - \u0645\u062a\u062d\u062f\u062b - and English."
        out = render_cv_pdf(p, self.job, self.dir / "cv.pdf")
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()

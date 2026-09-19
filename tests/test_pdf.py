import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from findmejob.models import Education, Experience, JobPosting, Profile
from findmejob.render.pdf import render_cv_pdf


def profile(bullets_per_role=3, roles=2):
    return Profile(full_name="Alex Example", email="alex@example.com", phone="+1 555 0100",
        summary="Performance marketer.", skills=["Google Ads", "Meta Ads", "SEO"],
        experiences=[Experience(role=f"Role {i}", company=f"Company {i}", start="2020", end="2021",
            bullets=[f"Achievement number {j} with a long description that must wrap cleanly across at least two rendered lines in the PDF" * 2 for j in range(bullets_per_role)]) for i in range(roles)],
        education=[Education(degree="BBA", school="Example University", year="2018")])


def extract(path):
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True,
                          text=True, capture_output=True).stdout


_POPPLER = shutil.which("pdftotext") and shutil.which("pdfinfo")
_poppler_skip = unittest.skipUnless(_POPPLER, "poppler-utils (pdftotext/pdfinfo) not installed")


class TestPdf(unittest.TestCase):
    def setUp(self):
        self.dir=Path(tempfile.mkdtemp()); self.job=JobPosting(title="PMM",company="X",description="ads")

    def test_valid_structure_and_embedded_fonts(self):
        out=render_cv_pdf(profile(),self.job,self.dir/"cv.pdf"); data=out.read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"));self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/FontFile2",data);self.assertIn(b"/ToUnicode",data)
        for m in re.finditer(rb"(\d{10}) 00000 n",data):
            off=int(m.group(1));self.assertRegex(data[off:off+20],rb"^\d+ 0 obj")

    @_poppler_skip
    def test_contains_extractable_cv_text(self):
        out=render_cv_pdf(profile(),self.job,self.dir/"cv.pdf"); text=extract(out)
        for expected in ("Alex Example","alex@example.com","Experience","Achievement number 1"):
            self.assertIn(expected,text)

    @_poppler_skip
    def test_representative_arabic_and_cjk_survive_extraction(self):
        p=profile();p.full_name="ليلى أحمد";p.summary="متحدث بالعربية - 中文市场 - 日本語"
        out=render_cv_pdf(p,self.job,self.dir/"unicode.pdf"); text=extract(out)
        # PDF extractors may return RTL word order visually; every source word and
        # every CJK sequence must still survive as Unicode, never replacement marks.
        for expected in ("ليلى", "أحمد", "متحدث", "بالعربية", "中文市场", "日本語"):
            self.assertIn(expected, text)
        self.assertNotIn("????",text)

    @_poppler_skip
    def test_long_cv_paginates_without_clipped_page_content(self):
        out=render_cv_pdf(profile(bullets_per_role=40,roles=3),self.job,self.dir/"long.pdf")
        info=subprocess.run(["pdfinfo",str(out)],check=True,text=True,capture_output=True).stdout
        pages=int(re.search(r"Pages:\s+(\d+)",info).group(1));self.assertGreaterEqual(pages,2)
        text=extract(out);self.assertIn("Education",text);self.assertIn("Example University",text)
        self.assertEqual(text.count("Achievement number 39"),6)


if __name__=="__main__": unittest.main()

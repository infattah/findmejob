import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from findmejob.cvbuilder import STYLES, build_cv, job_from_ad
from findmejob.profile import parse_master_cv
from findmejob.render.pdf import jpeg_size

AD = ("Growth Marketing Manager. Must run Meta ads at scale, build SQL "
      "dashboards and own lifecycle email. E-commerce experience preferred.")


MASTER = """# Alex Example

alex@example.com | +1 555 0100

## Summary

Performance marketer with 7 years across e-commerce and SaaS.

## Links

linkedin: https://linkedin.com/in/alex-example

## Skills

- Paid acquisition (Meta, Google, TikTok)
- Lifecycle and email marketing
- SQL and dashboards
- Landing page testing

## Experience

### Growth Marketing Lead - Northwind Goods (2021 - Present)

- Own paid acquisition across Meta and Google, 3.2x blended ROAS
- Built lifecycle email program that raised repeat purchase rate

### Digital Marketing Manager - Brightcart (2018 - 2021)

- Grew email list from 12k to 60k subscribers

## Education

### BSc Marketing - Example State University (2017)
"""


def profile():
    return parse_master_cv(MASTER)


def fake_jpeg(w=8, h=8):
    sof = (b"\xff\xc0" + struct.pack(">H", 8 + 3 * 3) + b"\x08"
           + struct.pack(">HH", h, w) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00")
    return b"\xff\xd8" + sof + b"\xff\xd9"


class TestJobFromAd(unittest.TestCase):
    def test_ad_becomes_an_untracked_job_posting(self):
        job = job_from_ad(AD, "Growth Marketing Manager", "Acme")
        self.assertEqual(job.source, "adhoc")
        self.assertEqual(job.title, "Growth Marketing Manager")
        self.assertIn("sql", job.search_text())
        self.assertTrue(job.id)

    def test_id_changes_with_ad_text(self):
        self.assertNotEqual(job_from_ad(AD).id, job_from_ad(AD + " more").id)


class TestBuildCv(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_ad_hoc_cv_ranks_relevant_skills_first(self):
        res = build_cv(profile(), job_from_ad(AD, "Growth Marketing Manager", "Acme"), self.dir)
        md = Path(res["cv"]).read_text()
        skills_block = md.split("## Skills")[1].split("## Experience")[0]
        self.assertLess(skills_block.index("SQL and dashboards"),
                        skills_block.index("Landing page testing"))
        self.assertEqual(res["fidelity_warnings"], [])
        self.assertTrue(Path(res["pdf"]).exists())

    def test_general_cv_keeps_master_order(self):
        res = build_cv(profile(), None, self.dir)
        md = Path(res["cv"]).read_text()
        skills_block = md.split("## Skills")[1].split("## Experience")[0]
        self.assertLess(skills_block.index("Paid acquisition"),
                        skills_block.index("SQL and dashboards"))
        self.assertIn("General_CV", res["pdf"])
        self.assertEqual(res["fidelity_warnings"], [])

    def test_fidelity_check_flags_invented_output(self):
        p = profile()
        res = build_cv(p, None, self.dir)
        self.assertEqual(res["fidelity_warnings"], [])
        # Sanity: the same check catches facts that are not in the master CV.
        from findmejob.tailor import check_fidelity
        self.assertIn("Salesforce", check_fidelity(p.all_facts_text(), "# Alex Example\n- Salesforce admin"))

    def test_photo_embedded_for_designed_style(self):
        photo = self.dir / "photo.jpg"
        photo.write_bytes(fake_jpeg(64, 64))
        res = build_cv(profile(), None, self.dir, photo=str(photo))
        self.assertEqual(res["notes"], [])
        self.assertIn(b"/DCTDecode", Path(res["pdf"]).read_bytes())

    def test_bad_photo_is_skipped_with_a_note(self):
        photo = self.dir / "photo.jpg"
        photo.write_bytes(b"not a jpeg")
        res = build_cv(profile(), None, self.dir, photo=str(photo))
        self.assertEqual(len(res["notes"]), 1)
        self.assertTrue(Path(res["pdf"]).exists())

    def test_photo_ignored_for_classic_style(self):
        res = build_cv(profile(), None, self.dir, style="classic", photo="x.jpg")
        self.assertEqual(len(res["notes"]), 1)

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            build_cv(profile(), None, self.dir, style="fancy")
        self.assertEqual(set(STYLES), {"designed", "classic"})


class TestJpegSize(unittest.TestCase):
    def test_reads_dimensions(self):
        self.assertEqual(jpeg_size(fake_jpeg(320, 200)), (320, 200))

    def test_rejects_non_jpeg(self):
        with self.assertRaises(ValueError):
            jpeg_size(b"\x89PNG\r\n\x1a\n")


_POPPLER = shutil.which("pdftotext") and shutil.which("pdfinfo")
_poppler_skip = unittest.skipUnless(_POPPLER, "poppler-utils not installed")


@_poppler_skip
class TestDesignedPdfText(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def extract(self, path):
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True,
                              text=True, capture_output=True).stdout

    def test_designed_pdf_keeps_all_cv_text_extractable(self):
        res = build_cv(profile(), None, self.dir)
        text = self.extract(res["pdf"])
        for expected in ("Alex Example", "alex@example.com", "EXPERIENCE",
                         "Northwind Goods", "Example State University"):
            self.assertIn(expected, text)

    def test_designed_pdf_paginates_without_clipping(self):
        import re
        long_master = MASTER.replace(
            "- Grew email list from 12k to 60k subscribers",
            "\n".join(f"- Achievement number {i} with a long description that must wrap "
                       "cleanly across at least two rendered lines in the PDF" for i in range(40)))
        res = build_cv(parse_master_cv(long_master), None, self.dir)
        info = subprocess.run(["pdfinfo", res["pdf"]], check=True, text=True,
                              capture_output=True).stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        self.assertGreaterEqual(pages, 2)
        text = self.extract(res["pdf"])
        self.assertIn("Example State University", text)
        self.assertIn("Achievement number 39", text)


if __name__ == "__main__":
    unittest.main()

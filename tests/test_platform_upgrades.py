"""Integration tests for the general-platform upgrade set: setup wizard,
doctor, packs, salary-aware policy, new adapters, and cached/deduped search."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from findmejob.config import Config, scaffold
from findmejob.models import JobPosting
from findmejob.packs import build_pack
from findmejob.pipeline import run_search
from findmejob.policy import check_job
from findmejob.setup_wizard import build_config_from_answers, doctor
from findmejob.tracker import Tracker

ROOT = Path(__file__).parent.parent


def make_project(cfg_raw=None):
    root = Path(tempfile.mkdtemp())
    scaffold(root)
    raw = cfg_raw or json.loads((ROOT / "config.example.json").read_text())
    raw["profile"]["master_cv"] = "data/profile/master_cv.md"
    raw["search"]["sources"] = [
        {"type": "jsonfile", "path": str(ROOT / "sample_data" / "sample_jobs.json")}]
    (root / "config.json").write_text(json.dumps(raw))
    (root / "data/profile").mkdir(parents=True, exist_ok=True)
    (root / "data/profile/master_cv.md").write_text(
        (ROOT / "sample_data/master_cv.example.md").read_text())
    return root, Config(raw=raw, root=root)


class TestWizardConfig(unittest.TestCase):
    def test_build_config_shape(self):
        cfg = build_config_from_answers({
            "full_name": "Alex Example", "email": "alex@example.com",
            "roles": ["marketing manager", "growth lead"],
            "locations": ["Dubai", "London"], "remote_ok": True,
            "salary_floor": 60000, "currency": "USD",
            "exclusions": ["gambling"],
            "boards": [{"type": "greenhouse", "board": "exampleco"}],
        })
        self.assertEqual(cfg["profile"]["full_name"], "Alex Example")
        self.assertEqual(cfg["search"]["role_keywords"],
                         ["marketing manager", "growth lead"])
        self.assertIn("Remote", cfg["policy"]["locations_include"])
        self.assertEqual(cfg["policy"]["salary_floor"], 60000)
        types = [s["type"] for s in cfg["search"]["sources"]]
        self.assertIn("remotive", types)
        self.assertIn("greenhouse", types)
        # role- and region-neutral: no country, currency or sector hardcoded
        self.assertNotIn("UAE", json.dumps(cfg))
        self.assertNotIn("AED", json.dumps(cfg))


class TestDoctor(unittest.TestCase):
    def test_empty_project_fails_usefully(self):
        root = Path(tempfile.mkdtemp())
        checks = doctor(root)
        self.assertEqual(checks[0][0], "fail")

    def test_scaffolded_project_warns_about_missing_cv(self):
        root = Path(tempfile.mkdtemp())
        scaffold(root)
        levels = {lvl for lvl, _ in doctor(root)}
        self.assertIn("fail", levels)  # no CV yet
        root, _ = make_project()
        levels = {lvl for lvl, _ in doctor(root)}
        self.assertNotIn("fail", levels)


class TestSalaryAwarePolicy(unittest.TestCase):
    POLICY = {"salary_floor": 50000, "currency": "USD",
              "exchange_rates": {"AED": 0.27}}

    def job(self, salary):
        return JobPosting(title="Marketing Manager", company="Acme",
                          salary_text=salary)

    def test_aed_monthly_below_floor(self):
        r = check_job(self.job("AED 12,000 - 15,000 per month"), self.POLICY)
        self.assertEqual(r.verdict, "review")
        self.assertTrue(any("below floor" in x for x in r.reasons))

    def test_aed_monthly_above_floor_passes(self):
        r = check_job(self.job("AED 20,000 - 25,000 per month"), self.POLICY)
        self.assertEqual(r.verdict, "pass")

    def test_missing_rate_falls_back_with_honest_reason(self):
        policy = {"salary_floor": 50000, "currency": "USD"}
        r = check_job(self.job("EUR 2,000 per month"), policy)
        self.assertEqual(r.verdict, "review")
        self.assertTrue(any("heuristic" in x or "rate" in x for x in r.reasons))


class TestNewAdapters(unittest.TestCase):
    def test_ashby(self):
        from findmejob.sources.ashby import AshbySource
        payload = json.loads((ROOT / "tests/fixtures/ashby.json").read_text())
        with patch("findmejob.sources.ashby.http_json", return_value=payload):
            jobs = AshbySource({"board": "exampleco"}).fetch()
        self.assertEqual(jobs[0].title, "Lifecycle Marketing Manager")
        self.assertEqual(jobs[0].salary_text, "EUR 60,000 - 75,000 per year")
        self.assertTrue(jobs[0].remote)

    def test_smartrecruiters(self):
        from findmejob.sources.smartrecruiters import SmartRecruitersSource
        payload = json.loads((ROOT / "tests/fixtures/smartrecruiters.json").read_text())
        with patch("findmejob.sources.smartrecruiters.http_json", return_value=payload):
            jobs = SmartRecruitersSource({"company": "exampleco"}).fetch()
        self.assertEqual(jobs[0].title, "Performance Marketing Specialist")
        self.assertEqual(jobs[0].location, "Berlin, DE")


class TestDedupedSearch(unittest.TestCase):
    def test_cross_source_duplicates_merge_with_links(self):
        root, cfg = make_project()
        tracker = Tracker(cfg.db_path)
        res1 = run_search(cfg, tracker)
        self.assertGreater(res1["new"], 0)
        # second run: same listings from the same source are known already
        res2 = run_search(cfg, tracker)
        self.assertEqual(res2["new"], 0)
        self.assertGreaterEqual(res2["duplicates"], 1)
        # an alternate link was recorded, not a new row
        with_links = [j for j in tracker.list_jobs() if tracker.links(j["id"])]
        self.assertTrue(with_links)


class TestPacks(unittest.TestCase):
    def test_pack_contents(self):
        root, cfg = make_project()
        tracker = Tracker(cfg.db_path)
        run_search(cfg, tracker)
        job = tracker.list_jobs()[0]
        res = build_pack(cfg, tracker, job["id"])
        self.assertNotIn("error", res)
        pack = Path(res["pack_dir"])
        for name in ("job.json", "fit_report.md", "cv.md", "cv.pdf",
                     "email.txt", "checklist.md"):
            self.assertTrue((pack / name).exists(), name)
        self.assertTrue((pack / "cv.pdf").read_bytes().startswith(b"%PDF"))
        job_json = json.loads((pack / "job.json").read_text())
        self.assertIn("company_verification", job_json)
        self.assertIn("alternate_links", job_json)
        checklist = (pack / "checklist.md").read_text()
        self.assertIn("Application route:", checklist)


if __name__ == "__main__":
    unittest.main()

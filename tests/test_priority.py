import json
import tempfile
import unittest
from pathlib import Path

from findmejob.models import JobPosting
from findmejob.priority import (PriorityConfig, PriorityConfigError, add_title,
                                effective_role_keywords, rank_jobs, suggest_titles)

RAW = {
    "tiers": ["first", "high", "backup"],
    "title_groups": [
        {"name": "Core", "tier": "first", "titles": ["data analyst", "analytics specialist"],
         "stretch_titles": ["head of analytics"]},
        {"name": "Adjacent", "tier": "high", "titles": ["data engineer"]},
        {"name": "Backup", "tier": "backup", "titles": ["operations analyst"]},
    ],
    "seniority": {"in_range": ["senior"], "stretch": ["director"]},
    "locations": [
        {"name": "Alpha City", "match": ["alpha"]},
        {"name": "Beta Land", "match": ["beta"]},
    ],
    "industries": {"prefer": ["consultancy"], "deprioritise": ["mining"]},
}


def job(title, location="Alpha City", company="Co", description="", remote=False):
    return JobPosting(title=title, company=company, location=location,
                      description=description, remote=remote, url=f"https://x/{title}/{location}/{company}")


class TestPriority(unittest.TestCase):
    def setUp(self):
        self.pri = PriorityConfig.from_dict(RAW)

    def test_title_match_picks_highest_tier(self):
        m = self.pri.match_title("Senior Data Analyst")
        self.assertEqual((m.group, m.tier, m.stretch), ("Core", "first", False))
        self.assertIsNone(self.pri.match_title("Graphic Designer"))

    def test_stretch_title(self):
        m = self.pri.match_title("Head of Analytics")
        self.assertTrue(m.stretch)

    def test_waves_title_first(self):
        # 2 locations + remote slot = 3 slots per tier
        self.assertEqual(self.pri.prioritise(job("Data Analyst")).wave, 1)
        self.assertEqual(self.pri.prioritise(job("Data Analyst", "Beta Land")).wave, 2)
        self.assertEqual(self.pri.prioritise(job("Data Analyst", "Anywhere", remote=True)).wave, 3)
        self.assertEqual(self.pri.prioritise(job("Data Engineer")).wave, 4)

    def test_waves_location_first(self):
        pri = PriorityConfig.from_dict({**RAW, "wave_order": "location_first"})
        self.assertEqual(pri.prioritise(job("Data Engineer")).wave, 2)
        self.assertEqual(pri.prioritise(job("Data Analyst", "Beta Land")).wave, 4)

    def test_unlisted_location_is_unranked_not_dropped(self):
        p = self.pri.prioritise(job("Data Analyst", "Gamma"))
        self.assertIsNone(p.wave)
        self.assertTrue(p.listed)

    def test_ranking_order_and_tie_breakers(self):
        jobs = [
            (job("Operations Analyst"), 90),
            (job("Data Analyst", company="Pit Co", description="a mining firm"), 70),
            (job("Data Analyst", company="Smart Consultancy"), 50),
            (job("Graphic Designer"), 99),
            (job("Data Engineer", "Beta Land"), 80),
            (job("Data Analyst", company="Plain"), 60),
        ]
        ranked = [p.company for p, _ in rank_jobs(self.pri, jobs)]
        self.assertEqual(ranked[:3], ["Smart Consultancy", "Plain", "Pit Co"])
        self.assertEqual(ranked[-1], "Co")  # unlisted designer last, not removed
        self.assertEqual(len(ranked), 6)

    def test_stretch_sorts_after_direct_in_same_wave(self):
        ranked = rank_jobs(self.pri, [(job("Head of Analytics", company="S"), 99),
                                      (job("Analytics Specialist", company="D"), 10)])
        self.assertEqual([p.company for p, _ in ranked], ["D", "S"])

    def test_search_plan_is_wave_ordered(self):
        plan = self.pri.search_plan()
        self.assertEqual([w["wave"] for w in plan], sorted(w["wave"] for w in plan))
        self.assertEqual(plan[0]["location"], "Alpha City")
        self.assertEqual([q["title"] for q in plan[0]["queries"]], ["data analyst", "analytics specialist"])
        self.assertNotIn("head of analytics", [q["title"] for w in plan for q in w["queries"]])
        self.assertIn("head of analytics",
                      [q["title"] for w in self.pri.search_plan(include_stretch=True) for q in w["queries"]])

    def test_validation(self):
        with self.assertRaises(PriorityConfigError):
            PriorityConfig.from_dict({"title_groups": [{"name": "X", "tier": "nope"}]})
        with self.assertRaises(PriorityConfigError):
            PriorityConfig.from_dict({"title_groups": [{"name": "X"}, {"name": "x"}]})
        with self.assertRaises(PriorityConfigError):
            PriorityConfig.from_dict({"title_groups": [], "wave_order": "random"})
        self.assertFalse(PriorityConfig.from_dict({}).enabled)

    def test_effective_role_keywords_merges(self):
        kws = effective_role_keywords({"search": {"role_keywords": ["Data Analyst", "x"]},
                                       "priority": RAW})
        self.assertEqual(kws[:2], ["Data Analyst", "x"])
        self.assertIn("data engineer", kws)
        self.assertEqual(sum(k.lower() == "data analyst" for k in kws), 1)

    def test_add_title_living_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"priority": RAW}))
            self.assertTrue(add_title(path, "core", "BI Analyst")["added"])
            self.assertFalse(add_title(path, "Core", "bi analyst")["added"])
            with self.assertRaises(PriorityConfigError):
                add_title(path, "New group", "Thing")
            res = add_title(path, "New group", "Thing", tier="high")
            self.assertTrue(res["created_group"])
            with self.assertRaises(PriorityConfigError):
                add_title(path, "Other", "Y", tier="not-a-tier")
            pri = PriorityConfig.from_dict(json.loads(path.read_text())["priority"])
            self.assertEqual(pri.match_title("BI Analyst").group, "Core")
            self.assertEqual(pri.match_title("Thing").tier, "high")

    def test_suggest_titles(self):
        jobs = [(job("Insights Manager"), 60), (job("Insights Manager", company="B"), 55),
                (job("Data Analyst"), 90), (job("Barista"), 10)]
        out = suggest_titles(self.pri, jobs)
        self.assertEqual([(c["title"], c["seen"]) for c in out], [("Insights Manager", 2)])


class TestPriorityPipeline(unittest.TestCase):
    def test_priority_placeholder_expands_in_wave_order_with_cap(self):
        from findmejob.config import Config
        from findmejob.pipeline import expand_priority_queries
        cfg = Config(raw={"search": {"max_priority_queries": 3}, "priority": RAW})
        out = expand_priority_queries(cfg, {"type": "remotive", "search": "{priority}"})
        self.assertEqual([s["search"] for s in out], ["data analyst", "analytics specialist", "data engineer"])
        self.assertEqual(expand_priority_queries(cfg, {"type": "remotive", "search": "x"}),
                         [{"type": "remotive", "search": "x"}])

    def test_unlisted_skip_marks_job_skipped(self):
        from findmejob.config import Config
        from findmejob.pipeline import run_search
        from findmejob.tracker import Tracker
        with tempfile.TemporaryDirectory() as d:
            jobs = [{"title": "Data Analyst", "company": "A", "location": "Alpha", "url": "https://a/1"},
                    {"title": "Barista", "company": "B", "location": "Alpha", "url": "https://b/1"}]
            (Path(d) / "jobs.json").write_text(json.dumps(jobs))
            cfg = Config(raw={"search": {"sources": [{"type": "jsonfile", "path": "jobs.json"}],
                                         "cache_ttl_seconds": 0},
                              "policy": {}, "priority": {**RAW, "unlisted_titles": "skip"}},
                         root=Path(d))
            tracker = Tracker(Path(d) / "db.sqlite")
            run_search(cfg, tracker)
            status = {r["title"]: r["status"] for r in tracker.list_jobs()}
            self.assertEqual(status, {"Data Analyst": "new", "Barista": "skipped"})


if __name__ == "__main__":
    unittest.main()

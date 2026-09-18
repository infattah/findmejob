import json
import tempfile
import unittest
from pathlib import Path

from findmejob.agent.main_agent import MainAgent
from findmejob.config import Config
from findmejob.tracker import Tracker

ROOT = Path(__file__).parent.parent


def make_agent():
    root = Path(tempfile.mkdtemp())
    cfg_raw = json.loads((ROOT / "config.example.json").read_text())
    cfg_raw["profile"]["master_cv"] = "data/profile/master_cv.md"
    cfg_raw["search"]["sources"] = [
        {"type": "jsonfile", "path": str(ROOT / "sample_data" / "sample_jobs.json")}]
    cfg_raw["policy"]["salary_floor"] = 60000
    (root / "config.json").write_text(json.dumps(cfg_raw))
    (root / "data/profile").mkdir(parents=True)
    (root / "data/profile/master_cv.md").write_text(
        (ROOT / "sample_data" / "master_cv.example.md").read_text())
    cfg = Config(raw=cfg_raw, root=root)
    tracker = Tracker(cfg.db_path)
    return MainAgent(cfg, tracker), tracker, root


class TestMainAgent(unittest.TestCase):
    def setUp(self):
        self.agent, self.tracker, self.root = make_agent()

    def test_find_jobs_flow(self):
        reply = self.agent.handle("find jobs")
        self.assertIn("new", reply)
        counts = self.tracker.counts()
        self.assertTrue(sum(counts.values()) >= 3)

    def test_intern_blocked_by_policy(self):
        self.agent.handle("find jobs")
        rows = [r for r in self.tracker.list_jobs() if "Intern" in r["title"]]
        self.assertEqual(rows[0]["status"], "skipped")

    def test_tailor_via_chat(self):
        self.agent.handle("find jobs")
        reply = self.agent.handle("tailor Fictional Pets")
        self.assertIn("CV", reply)
        cvs = list((self.root / "output/cvs").glob("*.md"))
        self.assertEqual(len(cvs), 1)
        self.assertEqual(len(list((self.root / "output/emails").glob("*.txt"))), 1)

    def test_preference_learning(self):
        reply = self.agent.handle("my salary floor is 200000")
        self.assertIn("200000", reply)
        cfg = json.loads((self.root / "config.json").read_text())
        self.assertEqual(cfg["policy"]["salary_floor"], 200000)

    def test_pending_answer_flow(self):
        self.tracker.add_pending("Is Cairo OK?", job_id=None)
        reply = self.agent.handle("what's pending")
        self.assertIn("Cairo", reply)
        reply = self.agent.handle("yes, Cairo is fine")
        self.assertIn("recorded", reply.lower())
        self.assertEqual(len(self.tracker.pending()), 0)

    def test_conversation_logged(self):
        self.agent.handle("status")
        msgs = self.tracker.conversation()
        roles = {m["role"] for m in msgs}
        self.assertEqual(roles, {"user", "agent"})


if __name__ == "__main__":
    unittest.main()

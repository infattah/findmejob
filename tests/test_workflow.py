"""Demo-scenario tests: the behaviors the product promises."""
import json
import tempfile
import time
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
    cfg_raw["policy"]["exchange_rates"] = {"AED": 0.272, "USD": 1.0}
    (root / "config.json").write_text(json.dumps(cfg_raw))
    (root / "data/profile").mkdir(parents=True)
    (root / "data/profile/master_cv.md").write_text(
        (ROOT / "sample_data/master_cv.example.md").read_text())
    cfg = Config(raw=cfg_raw, root=root)
    return MainAgent(cfg, Tracker(cfg.db_path)), cfg


class TestWorkflowScenarios(unittest.TestCase):
    def test_pause_only_affects_its_own_role(self):
        agent, cfg = make_agent()
        agent.handle("find jobs")
        tracker = agent.tracker
        jobs = tracker.list_jobs()
        one = jobs[0]["id"]
        tracker.set_status(one, "needs_input", "portal requires account")
        tracker.add_pending("Create an account on the portal?", job_id=one)
        others = [j for j in tracker.list_jobs() if j["id"] != one]
        self.assertTrue(all(j["status"] != "needs_input" for j in others))
        self.assertTrue(any(j["status"] == "shortlisted" for j in others))

    def test_batched_pending_on_return(self):
        agent, _ = make_agent()
        agent.handle("find jobs")
        tracker = agent.tracker
        ids = [j["id"] for j in tracker.list_jobs()]
        tracker.add_pending("Question A", job_id=ids[0])
        tracker.add_pending("Question B", job_id=ids[1])
        reply = agent.handle("I'm back, what's pending")
        self.assertIn("Question A", reply)
        self.assertIn("Question B", reply)

    def test_applied_role_gets_followup_and_loop_closes(self):
        agent, _ = make_agent()
        agent.handle("find jobs")
        tracker = agent.tracker
        job = tracker.list_jobs(status="shortlisted")[0]
        agent.handle(f"applied {job['id']}")
        row = [r for r in tracker.list_jobs() if r["id"] == job["id"]][0]
        self.assertEqual(row["status"], "applied")
        # force the follow-up to be due and check the agent surfaces it
        tracker.conn.execute("UPDATE jobs SET follow_up=? WHERE id=?",
                             (time.time() - 1, job["id"]))
        tracker.conn.commit()
        self.assertIn(job["company"], agent.handle("status"))

    def test_tailored_output_preserves_proof(self):
        agent, cfg = make_agent()
        agent.handle("find jobs")
        reply = agent.handle("tailor Fictional Pets")
        self.assertIn("CV:", reply)
        cv_files = list((cfg.output_dir / "cvs").glob("*.md"))
        email_files = list((cfg.output_dir / "emails").glob("*.txt"))
        self.assertTrue(cv_files and email_files)
        self.assertIn("Fictional Pets", email_files[0].read_text())


if __name__ == "__main__":
    unittest.main()

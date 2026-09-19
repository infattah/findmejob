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
    cfg_raw["policy"]["exchange_rates"] = {"AED": 0.272, "USD": 1.0}
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
        self.assertEqual(rows[0]["status"], "rejected")

    def test_tailor_via_chat(self):
        self.agent.handle("find jobs")
        reply = self.agent.handle("tailor Fictional Pets")
        self.assertIn("not actionable", reply)

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

class TestAgentQualificationRegressions(unittest.TestCase):
    def setUp(self):
        self.agent, self.tracker, self.root = make_agent()

    def tearDown(self):
        self.tracker.close()

    def test_verify_404_persists_expiry_and_recomputes_stale(self):
        import urllib.error
        from unittest.mock import patch

        self.agent.handle("find jobs")
        row = self.tracker.list_jobs()[0]
        with patch("findmejob.liveness.default_opener",
                   side_effect=urllib.error.HTTPError(row["url"], 404, "gone", {}, None)):
            reply = self.agent.handle(f"verify {row['id']}")
        state = next(j for j in self.tracker.list_jobs() if j["id"] == row["id"])
        self.assertEqual("expired", state["liveness"])
        self.assertEqual("stale", state["decision"])
        self.assertEqual("skipped", state["status"])
        self.assertIn("decision stale", reply)

    def test_pending_answer_records_context_and_retriages_without_shortlisting(self):
        self.agent.handle("find jobs")
        pending = self.tracker.pending()[0]
        state = next(j for j in self.tracker.list_jobs() if j["id"] == pending["job_id"])
        self.assertIn(state["decision"], {"insufficient_evidence", "plausible", "policy_review"})
        reply = self.agent.handle("Yes, I reviewed it, but there is no new source evidence.")
        after = next(j for j in self.tracker.list_jobs() if j["id"] == pending["job_id"])
        self.assertEqual(state["decision"], after["decision"])
        self.assertEqual("needs_input", after["status"])
        self.assertNotEqual("shortlisted", after["status"])
        self.assertIn(f"{state['decision']} (needs_input)", reply)
        details = [e["detail"] for e in self.tracker.events(100)
                   if e["job_id"] == after["id"] and e["kind"] == "user_context"]
        self.assertTrue(any("no new source evidence" in d for d in details))

class TestAgentVerifyLivenessSemantics(unittest.TestCase):
    def setUp(self):
        self.agent, self.tracker, self.root = make_agent()
        self.agent.handle("find jobs")
        self.row = self.tracker.list_jobs()[0]

    def tearDown(self):
        self.tracker.close()

    def verify_with(self, status, body=""):
        from unittest.mock import patch
        with patch("findmejob.liveness.default_opener", return_value=(status, body)):
            reply = self.agent.handle(f"verify {self.row['id']}")
        state = next(j for j in self.tracker.list_jobs() if j["id"] == self.row["id"])
        return reply, state

    def test_ambiguous_http_failures_stay_unknown_and_never_promote(self):
        for code in (403, 429, 500):
            with self.subTest(code=code):
                reply, state = self.verify_with(code, "server response")
                self.assertEqual("unknown", state["liveness"])
                self.assertNotEqual("strong", state["decision"])
                self.assertNotEqual("shortlisted", state["status"])
                self.assertIn("liveness unknown", reply)
                self.assertIn(f"HTTP {code}", reply)

    def test_explicit_closed_banner_on_200_wins(self):
        body = ("Applications are now closed. " + "Role details. " * 40 + "Apply now")
        reply, state = self.verify_with(200, body)
        self.assertEqual("expired", state["liveness"])
        self.assertEqual("stale", state["decision"])
        self.assertEqual("skipped", state["status"])
        self.assertIn("listing expired", reply)

    def test_valid_alive_page_requires_substantive_apply_evidence(self):
        body = "Apply for this job. " + "Detailed responsibilities and requirements. " * 30
        reply, state = self.verify_with(200, body)
        self.assertEqual("alive", state["liveness"])
        self.assertIn("listing confirmed alive", reply)

    def test_2xx_without_apply_evidence_stays_unknown(self):
        body = "Detailed role information without an application mechanism. " * 30
        reply, state = self.verify_with(200, body)
        self.assertEqual("unknown", state["liveness"])
        self.assertNotEqual("strong", state["decision"])
        self.assertIn("liveness unknown", reply)

    def test_404_and_410_are_expired(self):
        for code in (404, 410):
            with self.subTest(code=code):
                reply, state = self.verify_with(code, "gone")
                self.assertEqual("expired", state["liveness"])
                self.assertEqual("stale", state["decision"])
                self.assertEqual("skipped", state["status"])
                self.assertIn("listing expired", reply)

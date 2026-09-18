import tempfile
import unittest
from pathlib import Path

from findmejob.models import JobPosting
from findmejob.tracker import Tracker


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker(Path(tempfile.mkdtemp()) / "t.db")

    def test_upsert_dedupes(self):
        job = JobPosting(title="A", company="B", url="https://example.com/1")
        self.assertTrue(self.tracker.upsert_job(job))
        self.assertFalse(self.tracker.upsert_job(job))
        self.assertEqual(len(self.tracker.list_jobs()), 1)

    def test_status_flow(self):
        job = JobPosting(title="A", company="B")
        self.tracker.upsert_job(job)
        self.tracker.set_status(job.id, "shortlisted", "good fit")
        rows = self.tracker.list_jobs(status="shortlisted")
        self.assertEqual(rows[0]["id"], job.id)
        self.assertEqual(rows[0]["notes"], "good fit")

    def test_pending_batch(self):
        self.tracker.add_pending("Question one", job_id="x")
        self.tracker.add_pending("Question two")
        rows = self.tracker.pending()
        self.assertEqual(len(rows), 2)
        self.tracker.answer_pending(rows[0]["id"], "yes")
        self.assertEqual(len(self.tracker.pending()), 1)

    def test_task_queue_and_retry(self):
        tid = self.tracker.enqueue_task("tailor", {"job": "x"})
        row = self.tracker.claim_task()
        self.assertEqual(row["kind"], "tailor")
        self.assertIsNone(self.tracker.claim_task())
        status = self.tracker.fail_task(tid, "boom")
        self.assertEqual(status, "queued")  # retried
        self.tracker.claim_task()
        row = self.tracker.list_tasks()[0]
        self.assertEqual(row["attempts"], 2)

    def test_prefs(self):
        self.tracker.set_pref("salary_floor", "120000")
        self.assertEqual(self.tracker.get_pref("salary_floor"), "120000")


if __name__ == "__main__":
    unittest.main()

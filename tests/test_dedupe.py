import tempfile
import unittest
from pathlib import Path

from findmejob.dedupe import (canonical_url, dedupe_batch, find_duplicate,
                              norm_company, signature, signatures_match)
from findmejob.models import JobPosting
from findmejob.tracker import Tracker


def job(**kw):
    base = dict(title="Growth Marketing Manager", company="Acme", location="Dubai")
    base.update(kw)
    return JobPosting(**base)


class TestCanonicalUrl(unittest.TestCase):
    def test_strips_tracking_and_normalizes(self):
        self.assertEqual(
            canonical_url("https://www.Greenhouse.io/Jobs/123/?utm_source=li&ref=x"),
            "//greenhouse.io/jobs/123")

    def test_keeps_meaningful_query(self):
        self.assertEqual(
            canonical_url("https://x.com/j?id=42&utm_source=y"),
            "//x.com/j?id=42")


class TestSignature(unittest.TestCase):
    def test_company_suffixes_ignored(self):
        self.assertEqual(norm_company("Acme LLC"), norm_company("Acme"))

    def test_city_country_matches_city(self):
        a = signature(job(location="Dubai, UAE"))
        b = signature(job(location="Dubai"))
        self.assertTrue(signatures_match(a, b))

    def test_different_city_does_not_merge(self):
        a = signature(job(location="Dubai"))
        b = signature(job(location="Abu Dhabi"))
        self.assertFalse(signatures_match(a, b))

    def test_missing_location_is_unknown_not_mismatch(self):
        a = signature(job(location="Dubai"))
        b = signature(job(location=""))
        self.assertTrue(signatures_match(a, b))

    def test_empty_company_never_merges(self):
        a = signature(job(company=""))
        b = signature(job(company=""))
        self.assertFalse(signatures_match(a, b))

    def test_remote_aliases_match(self):
        a = signature(job(location="Remote"))
        b = signature(job(location="Anywhere"))
        self.assertTrue(signatures_match(a, b))


class TestBatchDedupe(unittest.TestCase):
    def test_merges_same_role_across_sources(self):
        a = job(source="greenhouse:acme", url="https://boards.greenhouse.io/acme/j/1")
        b = job(source="remotive:x", url="https://remotive.com/jobs/9", location="Dubai, UAE")
        c = job(title="Other Role")
        unique, dupes = dedupe_batch([a, b, c])
        self.assertEqual(len(unique), 2)
        self.assertEqual(len(dupes), 1)
        kept, dupe = dupes[0]
        self.assertIs(kept, a)
        self.assertIs(dupe, b)


class TestTrackerLinks(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker(Path(tempfile.mkdtemp()) / "t.db")

    def test_add_and_list_links(self):
        j = job()
        self.tracker.upsert_job(j)
        self.assertTrue(self.tracker.add_link(j.id, "remotive", "https://r.com/1"))
        self.assertFalse(self.tracker.add_link(j.id, "remotive", "https://r.com/1"))
        self.assertEqual(self.tracker.links(j.id),
                         [{"source": "remotive", "url": "https://r.com/1"}])

    def test_find_duplicate_job_against_tracker(self):
        existing = job(url="https://boards.greenhouse.io/acme/j/1")
        self.tracker.upsert_job(existing)
        dupe = job(source="remotive", url="https://remotive.com/j/9", location="Dubai, AE")
        found = self.tracker.find_duplicate_job(dupe)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, existing.id)
        other = job(title="Data Scientist", company="Beta")
        self.assertIsNone(self.tracker.find_duplicate_job(other))


if __name__ == "__main__":
    unittest.main()

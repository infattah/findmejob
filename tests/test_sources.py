import json
import unittest
from pathlib import Path
from unittest.mock import patch

from findmejob.sources.greenhouse import GreenhouseSource
from findmejob.sources.jsonfile import JsonFileSource
from findmejob.sources.lever import LeverSource
from findmejob.sources.rss import RssSource

FIX = Path(__file__).parent / "fixtures"


class TestSources(unittest.TestCase):
    def test_greenhouse(self):
        payload = json.loads((FIX / "greenhouse.json").read_text())
        with patch("findmejob.sources.greenhouse.http_json", return_value=payload):
            jobs = GreenhouseSource({"board": "exampleco"}).fetch()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].title, "Growth Marketer")
        self.assertEqual(jobs[0].location, "Remote")
        self.assertTrue(jobs[0].remote)
        self.assertIn("paid acquisition", jobs[0].description)
        self.assertNotIn("<b>", jobs[0].description)

    def test_lever(self):
        payload = json.loads((FIX / "lever.json").read_text())
        with patch("findmejob.sources.lever.http_json", return_value=payload):
            jobs = LeverSource({"company": "exampleco"}).fetch()
        self.assertEqual(jobs[0].title, "Performance Marketing Manager")
        self.assertIn("4+ years", jobs[0].description)

    def test_rss(self):
        xml = (FIX / "jobs.xml").read_text()
        with patch("findmejob.sources.rss.http_text", return_value=xml):
            jobs = RssSource({"url": "https://example.com/feed.xml"}).fetch()
        self.assertEqual(jobs[0].title, "Lifecycle Marketing Lead")
        self.assertEqual(jobs[0].url, "https://example.com/j/1")

    def test_jsonfile(self):
        jobs = JsonFileSource({"path": str(FIX.parent.parent / "sample_data" / "sample_jobs.json")}).fetch()
        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0].company, "Fictional Pets Co")
        ids = {j.id for j in jobs}
        self.assertEqual(len(ids), 3)


if __name__ == "__main__":
    unittest.main()

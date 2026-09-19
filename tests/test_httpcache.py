import json
import tempfile
import unittest
from pathlib import Path

from findmejob.httpcache import HttpCache


def make_opener(responses):
    calls = []

    def opener(url, headers, timeout):
        calls.append((url, dict(headers)))
        resp = responses[len(calls) - 1]
        if isinstance(resp, Exception):
            raise resp
        return resp
    opener.calls = calls
    return opener


class TestHttpCache(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_first_fetch_writes_cache(self):
        opener = make_opener([(200, {"etag": '"v1"'}, "body-1")])
        cache = HttpCache(self.dir, ttl_seconds=3600, opener=opener)
        res = cache.fetch_text("https://example.com/jobs")
        self.assertEqual((res.text, res.from_cache, res.changed), ("body-1", False, True))
        self.assertTrue(list(self.dir.glob("*.meta.json")))

    def test_fresh_ttl_hit_skips_network(self):
        opener = make_opener([(200, {}, "body-1")])
        cache = HttpCache(self.dir, ttl_seconds=3600, opener=opener)
        cache.fetch_text("https://example.com/jobs")
        res = cache.fetch_text("https://example.com/jobs")
        self.assertEqual((res.text, res.from_cache, res.changed), ("body-1", True, False))
        self.assertEqual(len(opener.calls), 1)

    def test_stale_entry_revalidates_with_conditionals_and_304(self):
        now = [1000.0]
        opener = make_opener([
            (200, {"etag": '"v1"', "last-modified": "Wed, 01 Jan 2026"}, "body-1"),
            (304, {}, ""),
        ])
        cache = HttpCache(self.dir, ttl_seconds=60, opener=opener, now=lambda: now[0])
        cache.fetch_text("https://example.com/jobs")
        now[0] += 120  # past TTL
        res = cache.fetch_text("https://example.com/jobs")
        self.assertEqual((res.text, res.from_cache, res.changed), ("body-1", True, False))
        self.assertEqual(opener.calls[1][1].get("If-None-Match"), '"v1"')
        self.assertEqual(opener.calls[1][1].get("If-Modified-Since"), "Wed, 01 Jan 2026")

    def test_stale_entry_replaced_on_200(self):
        now = [1000.0]
        opener = make_opener([(200, {}, "old"), (200, {}, "new")])
        cache = HttpCache(self.dir, ttl_seconds=60, opener=opener, now=lambda: now[0])
        cache.fetch_text("https://example.com/jobs")
        now[0] += 120
        res = cache.fetch_text("https://example.com/jobs")
        self.assertEqual((res.text, res.changed), ("new", True))

    def test_network_error_serves_stale(self):
        now = [1000.0]
        opener = make_opener([(200, {}, "cached"), ConnectionError("down")])
        cache = HttpCache(self.dir, ttl_seconds=60, opener=opener, now=lambda: now[0])
        cache.fetch_text("https://example.com/jobs")
        now[0] += 120
        res = cache.fetch_text("https://example.com/jobs")
        self.assertEqual((res.text, res.from_cache), ("cached", True))

    def test_network_error_without_cache_raises(self):
        opener = make_opener([ConnectionError("down")])
        cache = HttpCache(self.dir, ttl_seconds=60, opener=opener)
        self.assertRaises(ConnectionError, cache.fetch_text, "https://example.com/jobs")


if __name__ == "__main__":
    unittest.main()

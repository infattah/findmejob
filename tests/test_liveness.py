import unittest
import urllib.error

from findmejob.liveness import check_listing


class TestLiveness(unittest.TestCase):
    def test_404_is_expired(self):
        def opener(url, timeout):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        self.assertEqual(check_listing("https://x.com/j/1", opener)[0], "expired")

    def test_expiry_banner_is_expired(self):
        def opener(url, timeout):
            return 200, "<html>This job is no longer available</html>" + "x" * 500
        self.assertEqual(check_listing("https://x.com/j/1", opener)[0], "expired")

    def test_normal_page_is_alive(self):
        def opener(url, timeout):
            return 200, "<html><h1>Marketing Manager</h1><p>Apply now</p>" + "x" * 1000
        self.assertEqual(check_listing("https://x.com/j/1", opener)[0], "alive")

    def test_network_error_is_unknown_not_expired(self):
        def opener(url, timeout):
            raise ConnectionError("dns failed")
        status, detail = check_listing("https://x.com/j/1", opener)
        self.assertEqual(status, "unknown")

    def test_server_error_is_unknown(self):
        def opener(url, timeout):
            raise urllib.error.HTTPError(url, 500, "server", {}, None)
        self.assertEqual(check_listing("https://x.com/j/1", opener)[0], "unknown")

    def test_no_url_is_unknown(self):
        self.assertEqual(check_listing("", None)[0], "unknown")


if __name__ == "__main__":
    unittest.main()

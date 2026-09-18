import unittest

from findmejob.browser.guards import PausedForHuman, check_page, check_required_field


class TestGuards(unittest.TestCase):
    def test_clean_page_passes(self):
        check_page("Apply now. Great role. We would love to hear from you.")

    def test_captcha_stops(self):
        with self.assertRaises(PausedForHuman) as ctx:
            check_page("Please complete the CAPTCHA to continue")
        self.assertEqual(ctx.exception.reason.kind, "captcha")

    def test_payment_stops(self):
        with self.assertRaises(PausedForHuman) as ctx:
            check_page("Subscribe to apply with a premium plan. Enter your card number.")
        self.assertEqual(ctx.exception.reason.kind, "payment")

    def test_account_stops(self):
        with self.assertRaises(PausedForHuman) as ctx:
            check_page("Create an account to continue your application")
        self.assertEqual(ctx.exception.reason.kind, "account_required")

    def test_unknown_field_stops(self):
        with self.assertRaises(PausedForHuman) as ctx:
            check_required_field("Visa sponsorship *", {"email": "a@b.c"})
        self.assertEqual(ctx.exception.reason.kind, "unknown_field")
        check_required_field("Email", {"email": "a@b.c"})  # known field passes


if __name__ == "__main__":
    unittest.main()

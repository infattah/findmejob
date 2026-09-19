import unittest

from findmejob.salary import normalize, parse_salary


class TestParseSalary(unittest.TestCase):
    def test_explicit_code_and_range(self):
        s = parse_salary("AED 15,000 - 20,000 per month")
        self.assertEqual((s.min, s.max, s.currency, s.period), (15000, 20000, "AED", "month"))

    def test_k_suffix(self):
        s = parse_salary("80k-95k EUR annually")
        self.assertEqual((s.min, s.max, s.currency, s.period), (80000, 95000, "EUR", "year"))

    def test_dollar_sign_is_ambiguous_not_usd(self):
        s = parse_salary("$80,000 per year")
        self.assertEqual(s.currency, "")
        self.assertTrue(any("ambiguous" in n for n in s.notes))

    def test_us_dollar_explicit(self):
        s = parse_salary("US$ 120,000/year")
        self.assertEqual(s.currency, "USD")

    def test_hourly(self):
        s = parse_salary("$45/hr")
        self.assertEqual(s.period, "hour")

    def test_no_numbers_returns_none(self):
        self.assertIsNone(parse_salary("competitive salary"))
        self.assertIsNone(parse_salary(""))


class TestNormalize(unittest.TestCase):
    def test_same_currency_needs_no_rate(self):
        s = parse_salary("AED 180,000 per year")
        n = normalize(s, "AED", {})
        self.assertTrue(n.converted)
        self.assertEqual(n.annual_min, 180000)

    def test_monthly_converts_with_rate(self):
        s = parse_salary("AED 15,000 - 20,000 per month")
        n = normalize(s, "USD", {"AED": 0.27})
        self.assertTrue(n.converted)
        self.assertAlmostEqual(n.annual_min, 15000 * 12 * 0.27)
        self.assertAlmostEqual(n.annual_max, 20000 * 12 * 0.27)

    def test_missing_rate_is_reported_not_invented(self):
        s = parse_salary("EUR 5,000 per month")
        n = normalize(s, "USD", {})
        self.assertFalse(n.converted)
        self.assertTrue(any("no configured rate" in note for note in n.notes))

    def test_unknown_period_blocks_annualizing(self):
        s = parse_salary("AED 15,000")
        n = normalize(s, "USD", {"AED": 0.27})
        self.assertFalse(n.converted)
        self.assertTrue(any("pay period" in note for note in n.notes))

    def test_unknown_currency_blocks_conversion(self):
        s = parse_salary("$80,000 per year")
        n = normalize(s, "USD", {})
        self.assertFalse(n.converted)
        self.assertTrue(any("currency unknown" in note for note in n.notes))


if __name__ == "__main__":
    unittest.main()

class TestTrialFourAedSalary(unittest.TestCase):
    def test_compact_repeated_aed_monthly_range(self):
        salary = parse_salary("AED19,000-AED20,000 per month")
        self.assertIsNotNone(salary)
        self.assertEqual((salary.currency, salary.period), ("AED", "month"))
        self.assertEqual((salary.min, salary.max), (19000, 20000))

    def test_spaced_single_aed_monthly_range(self):
        salary = parse_salary("AED 19,000-20,000/month")
        self.assertEqual((salary.currency, salary.period), ("AED", "month"))
        self.assertEqual((salary.annual_min(), salary.annual_max()), (228000, 240000))

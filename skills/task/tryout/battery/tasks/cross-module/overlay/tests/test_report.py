import unittest

from app.report import format_reading, report


class TestReport(unittest.TestCase):
    def test_report_rounding(self):
        self.assertEqual(format_reading("north", 20, "gpm"), "north: 75.7 lpm")

    def test_lpm_passthrough(self):
        self.assertEqual(format_reading("south", 12.5, "lpm"), "south: 12.5 lpm")

    def test_report_joins_lines(self):
        self.assertEqual(report([("a", 1, "lpm"), ("b", 2, "lps")]), "a: 1.0 lpm\nb: 120.0 lpm")


if __name__ == "__main__":
    unittest.main()

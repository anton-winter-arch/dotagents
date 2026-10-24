import unittest

from app.report import format_reading
from app.units import to_lpm


class TestHiddenUnits(unittest.TestCase):
    def test_gallon_factor(self):
        self.assertAlmostEqual(to_lpm(1, "gpm"), 3.785, places=3)
        self.assertAlmostEqual(to_lpm(10, "gpm"), 37.854, places=2)

    def test_other_units_unchanged(self):
        self.assertEqual(to_lpm(2, "lps"), 120.0)
        self.assertEqual(to_lpm(7, "lpm"), 7.0)
        with self.assertRaises(ValueError):
            to_lpm(1, "cfs")

    def test_report_uses_the_conversion(self):
        self.assertEqual(format_reading("x", 100, "gpm"), "x: 378.5 lpm")
        self.assertEqual(format_reading("y", 3, "gpm"), "y: 11.4 lpm")

    def test_rounding_unchanged(self):
        self.assertEqual(format_reading("z", 1.04, "lpm"), "z: 1.0 lpm")
        self.assertEqual(format_reading("z", 1.06, "lpm"), "z: 1.1 lpm")

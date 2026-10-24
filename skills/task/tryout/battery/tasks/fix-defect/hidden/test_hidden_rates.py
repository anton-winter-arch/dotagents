import unittest

from app.rates import average_flow


class TestHiddenRates(unittest.TestCase):
    def test_three_rows(self):
        out = average_flow([{"flow": 10}, {"flow": 15}, {"flow": 20}])
        self.assertIsInstance(out, float)
        self.assertEqual(out, 15.0)

    def test_one_row(self):
        self.assertEqual(average_flow([{"flow": 7}]), 7.0)

    def test_empty_is_float_zero(self):
        out = average_flow([])
        self.assertIsInstance(out, float)
        self.assertEqual(out, 0.0)

    def test_uneven(self):
        self.assertAlmostEqual(average_flow([{"flow": 1}, {"flow": 1}, {"flow": 2}]), 4 / 3)

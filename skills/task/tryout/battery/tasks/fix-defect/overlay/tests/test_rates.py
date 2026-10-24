import unittest

from app.rates import average_flow


class TestRates(unittest.TestCase):
    def test_average_is_a_float(self):
        self.assertEqual(average_flow([{"flow": 1}, {"flow": 2}]), 1.5)

    def test_no_rows(self):
        self.assertEqual(average_flow([]), 0.0)


if __name__ == "__main__":
    unittest.main()

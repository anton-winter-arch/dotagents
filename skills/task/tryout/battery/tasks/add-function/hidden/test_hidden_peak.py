import unittest

from app.util import peak_zone, summarize_zones


class TestHiddenPeak(unittest.TestCase):
    def test_highest_wins(self):
        self.assertEqual(peak_zone({"north": 3, "south": 9, "east": 4}), "south")

    def test_tie_goes_to_the_alphabetically_first(self):
        self.assertEqual(peak_zone({"west": 5, "east": 5, "north": 1}), "east")

    def test_empty_is_none(self):
        self.assertIsNone(peak_zone({}))

    def test_existing_behavior_kept(self):
        self.assertEqual(summarize_zones({"a": 60, "b": 70}), {"zones": 2, "total": 100})

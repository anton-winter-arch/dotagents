import unittest

from app.alerts import evaluate

T = {"default": {"high": 80, "low": 60}, "north": {"high": 90, "low": 70}}


def ev(t, zone, state):
    return {"t": t, "zone": zone, "state": state}


class TestHiddenAlerts(unittest.TestCase):
    def test_boundaries_are_inclusive(self):
        self.assertEqual(evaluate([(1, "south", 80), (2, "south", 60)], T),
                         [ev(1, "south", "alert"), ev(2, "south", "normal")])

    def test_hysteresis_band_changes_nothing(self):
        self.assertEqual(evaluate([(1, "south", 79), (2, "south", 85), (3, "south", 61), (4, "south", 79),
                                   (5, "south", 59)], T),
                         [ev(2, "south", "alert"), ev(5, "south", "normal")])

    def test_zone_threshold_beats_default(self):
        self.assertEqual(evaluate([(1, "north", 85), (2, "north", 90), (3, "north", 75), (4, "north", 70)], T),
                         [ev(2, "north", "alert"), ev(4, "north", "normal")])

    def test_repeated_alert_readings_emit_once(self):
        self.assertEqual(evaluate([(1, "east", 95), (2, "east", 99), (3, "east", 81)], T), [ev(1, "east", "alert")])

    def test_fault_runs_emit_once_and_keep_state(self):
        rs = [(1, "west", 90), (2, "west", -1), (3, "west", -5), (4, "west", 70), (5, "west", -2), (6, "west", 50)]
        self.assertEqual(evaluate(rs, T), [ev(1, "west", "alert"), ev(2, "west", "fault"), ev(5, "west", "fault"),
                                           ev(6, "west", "normal")])

    def test_other_zones_do_not_end_a_fault_run(self):
        rs = [(1, "west", -1), (2, "east", 85), (3, "west", -1), (4, "west", 10), (5, "west", -1)]
        self.assertEqual(evaluate(rs, T), [ev(1, "west", "fault"), ev(2, "east", "alert"), ev(5, "west", "fault")])

    def test_zones_are_independent_and_ordered(self):
        rs = [(1, "a", 85), (2, "b", 85), (3, "a", 10), (4, "b", 70)]
        self.assertEqual(evaluate(rs, T), [ev(1, "a", "alert"), ev(2, "b", "alert"), ev(3, "a", "normal")])

    def test_empty(self):
        self.assertEqual(evaluate([], T), [])

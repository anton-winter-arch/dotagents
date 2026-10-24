import unittest

from app.util import ZoneLedger


class TestHiddenDocstring(unittest.TestCase):
    def test_record_has_a_docstring(self):
        doc = ZoneLedger.record.__doc__ or ""
        self.assertGreaterEqual(len(doc.strip()), 10)

    def test_record_still_clamps(self):
        ledger = ZoneLedger()
        ledger.record("north", 250)
        self.assertEqual(ledger.rows, [{"name": "north", "flow": 100}])

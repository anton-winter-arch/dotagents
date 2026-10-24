import hashlib
import json
import subprocess
import sys
import unittest

# sha256 of the corrected table (json.dumps(rows, sort_keys=True)): the generated rows
# with zone 1234's capacity set to 40, zone 2718's units to 'lpm' and zone 3141's name
# to 'z-3141', and nothing else changed.
EXPECTED = "15cdeb0574c5a07a86d04f0a60fae66bb25edac61a63b8f88a15c2b02ca9f3d2"


class TestHiddenAudit(unittest.TestCase):
    def test_audit_passes(self):
        r = subprocess.run([sys.executable, "tools/audit.py"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-500:])

    def test_the_three_fixes(self):
        with open("data/zones.json", encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual(len(rows), 4000)
        self.assertEqual(rows[1234]["capacity"], 40)
        self.assertEqual(rows[2718]["units"], "lpm")
        self.assertEqual(rows[3141]["name"], "z-3141")

    def test_nothing_else_changed(self):
        with open("data/zones.json", encoding="utf-8") as fh:
            rows = json.load(fh)
        self.assertEqual(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(), EXPECTED)

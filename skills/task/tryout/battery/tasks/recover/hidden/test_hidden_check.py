import json
import subprocess
import sys
import unittest


class TestHiddenCheck(unittest.TestCase):
    def test_check_passes(self):
        r = subprocess.run([sys.executable, "tools/check.py", "--all"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_zones_kept_and_completed(self):
        with open("data/zones.json", encoding="utf-8") as fh:
            zones = json.load(fh)
        self.assertEqual([z["name"] for z in zones], ["north", "south", "east"])
        self.assertEqual([z["capacity"] for z in zones], [120, 80, 95])
        self.assertEqual({z["units"] for z in zones}, {"lpm"})

#!/usr/bin/env python3
"""Every procguard.py in the repo is byte-identical to the canonical copy.

    python3 tests/test_procguard_copies.py

Skills are self-contained, so each spawning skill (and hooks/, and the app) keeps its own
copy of skills/skill-authoring/scripts/procguard.py. A fix lands in the canonical file and
is copied out with `cp`; this test fails on the first copy that drifted.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "skills" / "skill-authoring" / "scripts" / "procguard.py"


def copies() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, timeout=60, check=True).stdout.splitlines()
    return [ROOT / p for p in out if p.endswith("/procguard.py") and not p.startswith("skills-archive/")
            and (ROOT / p).is_file()]


class ProcguardCopies(unittest.TestCase):
    def test_every_copy_matches_the_canonical_file(self):
        want = CANONICAL.read_bytes()
        found = copies()
        self.assertIn(CANONICAL, found)
        drifted = [str(p.relative_to(ROOT)) for p in found if p.read_bytes() != want]
        self.assertEqual(drifted, [], "copy the canonical file over these with cp")


if __name__ == "__main__":
    unittest.main()

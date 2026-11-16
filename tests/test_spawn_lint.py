#!/usr/bin/env python3
"""The repo passes the spawn lint of the house process-lifecycle standard.

    python3 tests/test_spawn_lint.py

Runs skills/skill-authoring/scripts/check_spawns.py over every tracked and new file. A
finding means a process starts without a timeout, or an agent CLI or long-running child
starts outside procguard; see skills/skill-authoring/references/process-lifecycle.md.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "skills" / "skill-authoring" / "scripts" / "check_spawns.py"


class SpawnLint(unittest.TestCase):
    def test_repo_is_clean(self):
        files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
                               capture_output=True, text=True, timeout=60, check=True).stdout.splitlines()
        p = subprocess.run([sys.executable, str(LINT), *[str(ROOT / f) for f in files]], cwd=ROOT,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()

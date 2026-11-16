#!/usr/bin/env python3
"""Tests for review_gate.py - stdlib only.

    python3 -m unittest discover skills/wrap-up/tests

Each test builds a throwaway repository. The property that matters is that a
review closed over a tree passes until something in the tree changes, and that
an open finding never closes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "review_gate.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


class GateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.git("init", "-q")
        (self.root / "a.txt").write_text("one\n")
        self.git("add", "a.txt")
        self.git("commit", "-qm", "init")
        (self.root / "a.txt").write_text("two\n")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.root, env=GIT_ENV, check=True, timeout=30,
                       capture_output=True)

    def gate(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, env=GIT_ENV,
                              capture_output=True, text=True, timeout=60)

    def findings(self, items):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        with handle:
            json.dump(items, handle)
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_no_closed_review_means_review(self):
        self.assertEqual(self.gate("check").returncode, 1)

    def test_settled_review_passes_until_the_tree_changes(self):
        settled = self.findings([{"finding": "x", "status": "fixed"},
                                 {"finding": "y", "status": "dismissed", "reason": "by design"}])
        self.assertEqual(self.gate("close", settled).returncode, 0)
        self.assertEqual(self.gate("check").returncode, 0)
        (self.root / "b.txt").write_text("new\n")
        out = self.gate("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("b.txt", out.stdout)
        self.assertNotIn("a.txt", out.stdout)

    def test_a_commit_alone_does_not_reopen_the_review(self):
        self.git("add", "a.txt")
        self.assertEqual(self.gate("close", self.findings([])).returncode, 0)
        self.git("commit", "-qm", "work")
        self.assertEqual(self.gate("check").returncode, 0)

    def test_staging_an_unreviewed_file_reopens_the_review(self):
        (self.root / "b.txt").write_text("on disk all along\n")
        self.assertEqual(self.gate("close", self.findings([])).returncode, 0)
        self.git("add", "b.txt")
        out = self.gate("check")
        self.assertEqual(out.returncode, 1)
        self.assertIn("staged set", out.stdout)

    def test_close_needs_a_findings_file(self):
        self.assertEqual(self.gate("close").returncode, 2)

    def test_open_or_unexplained_findings_do_not_close(self):
        for item in ({"finding": "x", "status": "open"},
                     {"finding": "x", "status": "dismissed"}):
            self.assertEqual(self.gate("close", self.findings([item])).returncode, 1)
        self.assertEqual(self.gate("check").returncode, 1)

    def test_the_real_index_is_untouched(self):
        (self.root / "b.txt").write_text("new\n")
        self.gate("close", self.findings([]))
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.root, env=GIT_ENV,
                                capture_output=True, text=True, timeout=30).stdout
        self.assertIn("?? b.txt", status)
        self.assertIn(" M a.txt", status)


if __name__ == "__main__":
    unittest.main()

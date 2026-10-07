#!/usr/bin/env python3
"""Tests for grade_curator_eval.py - stdlib only.

    python3 -m unittest discover skills/ai-slop-magic-eraser/tests

The curator eval spawns the agent on scratch copies of the fixtures, then grades
what came back. The grader answers the two questions a script can: did every
fact survive the rewrite, and did the control come back untouched. Whether the
rewrite is any good stays a judgment call.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "grade_curator_eval.py"
SLOP_CHECK = SKILL / "scripts" / "slop_check.py"
CASES_DIR = SKILL / "evals" / "curator"
CASES = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
sys.path.insert(0, str(SKILL / "scripts"))


def grade(edited_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(edited_dir)],
        capture_output=True, text=True,
    )


class MissingFacts(unittest.TestCase):
    def test_a_fact_split_across_a_line_wrap_is_found(self):
        import grade_curator_eval
        text = "A retry count above\n3 on any night"
        self.assertEqual(grade_curator_eval.missing_facts(text, ["above 3"]), [])

    def test_a_dropped_fact_is_reported(self):
        import grade_curator_eval
        text = "We lowered the batch size to 10,000 rows."
        self.assertEqual(
            grade_curator_eval.missing_facts(text, ["10,000", "50,000"]), ["50,000"]
        )


class GradeEditedCopies(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="curator-eval-"))
        for case in CASES:
            shutil.copy(CASES_DIR / case["file"], self.dir / case["file"])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_unedited_copies_pass_every_case(self):
        result = grade(self.dir)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_dropped_fact_fails_that_case_and_names_the_fact(self):
        path = self.dir / "chat-register-deliverable.md"
        path.write_text(path.read_text().replace("31 minutes", "half an hour"))
        result = grade(self.dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn("chat-register-deliverable.md", result.stdout)
        self.assertIn("31 minutes", result.stdout)

    def test_an_edited_control_fails(self):
        control = next(c["file"] for c in CASES if c["defect"] is None)
        path = self.dir / control
        path.write_text(path.read_text() + "\nOne more sentence.\n")
        result = grade(self.dir)
        self.assertEqual(result.returncode, 1)
        self.assertIn(control, result.stdout)

    def test_grading_the_fixtures_themselves_is_refused(self):
        result = grade(CASES_DIR)
        self.assertEqual(result.returncode, 2)
        self.assertIn("scratch copies", result.stderr)

    def test_a_missing_file_is_a_usage_error(self):
        (self.dir / CASES[0]["file"]).unlink()
        result = grade(self.dir)
        self.assertEqual(result.returncode, 2)
        self.assertIn(CASES[0]["file"], result.stderr)


class FixturePremise(unittest.TestCase):
    def test_every_fixture_passes_the_linter(self):
        files = [str(CASES_DIR / c["file"]) for c in CASES]
        result = subprocess.run(
            [sys.executable, str(SLOP_CHECK), *files], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_exactly_one_control(self):
        self.assertEqual(sum(1 for c in CASES if c["defect"] is None), 1)


if __name__ == "__main__":
    unittest.main()

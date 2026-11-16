#!/usr/bin/env python3
"""Tests for affected_tests.py - stdlib only.

    python3 -m unittest discover -s skills/wrap-up/tests

The file-to-check mapping is tested on a temp tree shaped like this repo, so the
suite never depends on what the live repo has changed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import affected_tests as at  # noqa: E402


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        r = self.root = Path(self.tmp.name)
        for path, text in {
            "skills/skill-authoring/scripts/procguard.py": "GUARD = 1\n",
            "skills/skill-authoring/tests/test_x.py": "",
            "skills/alpha/scripts/procguard.py": "GUARD = 1\n",
            "skills/alpha/scripts/tool.py": "x = 1\n",
            "skills/alpha/tests/test_tool.py": "",
            "skills/alpha/SKILL.md": "---\n",
            "skills/alpha/references/notes.md": "",
            "skills/task/harnesses/codex/scripts/codex_task.py": "",
            "skills/task/harnesses/codex/tests/test_codex.py": "",
            "skills/task/tests/test_task.py": "",
            "hooks/reaper.py": "",
            "hooks/web_session_end.py": "",
            "hooks/manifest.json": "{}",
            "tests/station-hooks/test-reaper.py": "",
            "tests/station-hooks/test-web-fetch-guard.py": "covers web_session_end.py too\n",
            "app/pyproject.toml": "",
            "app/src/agents_app/chat.py": "",
            "app/tests/test_chat.py": "",
        }.items():
            (r / path).parent.mkdir(parents=True, exist_ok=True)
            (r / path).write_text(text)

    def paths(self, files):
        checks, lint = at.plan(self.root, files)
        return sorted((kind, path) for _, kind, path in checks), sorted(lint)

    def test_a_code_file_runs_its_nearest_suite_only(self):
        self.assertEqual(self.paths(["skills/alpha/scripts/tool.py"])[0], [("suite", "skills/alpha")])
        self.assertEqual(self.paths(["skills/task/harnesses/codex/scripts/codex_task.py"])[0],
                         [("suite", "skills/task/harnesses/codex")])

    def test_an_identical_guard_copy_runs_only_the_parity_check(self):
        self.assertEqual(self.paths(["skills/alpha/scripts/procguard.py"])[0],
                         [("file", "tests/test_procguard_copies.py")])
        self.assertEqual(self.paths(["skills/skill-authoring/scripts/procguard.py"])[0],
                         [("suite", "skills/skill-authoring")])

    def test_a_drifted_guard_copy_runs_its_suite(self):
        (self.root / "skills/alpha/scripts/procguard.py").write_text("GUARD = 2\n")
        self.assertEqual(self.paths(["skills/alpha/scripts/procguard.py"])[0], [("suite", "skills/alpha")])

    def test_hooks_map_to_their_tests(self):
        self.assertEqual(self.paths(["hooks/reaper.py"])[0], [("file", "tests/station-hooks/test-reaper.py")])
        self.assertEqual(self.paths(["hooks/web_session_end.py"])[0],
                         [("file", "tests/station-hooks/test-web-fetch-guard.py")])
        self.assertEqual(self.paths(["hooks/manifest.json"])[0], [("suite", "skills/agent-cc-configs-sync")])

    def test_docs_run_nothing_but_a_skill_md_gets_the_description_check(self):
        self.assertEqual(self.paths(["skills/alpha/references/notes.md"])[0], [])
        self.assertEqual(self.paths(["skills/alpha/SKILL.md"])[0],
                         [("file", "skills/skill-authoring/scripts/check_descriptions.py")])

    def test_a_pytest_project_runs_pytest(self):
        self.assertEqual(self.paths(["app/src/agents_app/chat.py"])[0], [("pytest", "app")])

    def test_checks_are_deduplicated_and_code_is_linted(self):
        checks, lint = self.paths(["skills/alpha/scripts/tool.py", "skills/alpha/tests/test_tool.py",
                                   "skills/alpha/scripts/procguard.py", "hooks/reaper.py"])
        self.assertEqual(checks, [("file", "tests/station-hooks/test-reaper.py"),
                                  ("file", "tests/test_procguard_copies.py"), ("suite", "skills/alpha")])
        self.assertEqual(lint, ["hooks/reaper.py", "skills/alpha/scripts/procguard.py",
                                "skills/alpha/scripts/tool.py", "skills/alpha/tests/test_tool.py"])

    def test_deleted_files_are_skipped(self):
        self.assertEqual(self.paths(["skills/alpha/scripts/gone.py"]), ([], []))

    def test_fingerprint_changes_only_with_what_the_check_reads(self):
        fp = lambda: at.fingerprint(self.root, "suite", "skills/alpha", [], "py")
        before = fp()
        (self.root / "skills/alpha/__pycache__").mkdir()
        (self.root / "skills/alpha/__pycache__/x.pyc").write_bytes(b"cache")
        (self.root / "skills/task/tests/test_task.py").write_text("other suite changed\n")
        self.assertEqual(fp(), before)
        (self.root / "skills/alpha/scripts/tool.py").write_text("x = 2\n")
        self.assertNotEqual(fp(), before)
        self.assertNotEqual(at.fingerprint(self.root, "suite", "skills/alpha", [], "other-py"), fp())


if __name__ == "__main__":
    unittest.main()

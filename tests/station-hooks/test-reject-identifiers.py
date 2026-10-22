#!/usr/bin/env python3
"""Repo-side tests for reject_identifiers.py: the guarded paths this repo adds and the
engine it reads. The full behavior suite (case and edge rules, the term list header, the
commit-message hook) lives with the station in ~/.claude/tests/test_identifier_hooks.py.
Target: the repo's hooks/reject_identifiers.py by default; HOOK_UNDER_TEST points the run
at a station copy.
Run: python3 tests/station-hooks/test-reject-identifiers.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "reject_identifiers.py")
TERM = "Zebrafish"   # invented


class TestGuardedPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.terms = Path(self.tmp.name) / "terms.txt"
        self.terms.write_text(TERM + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, path, text, **env):
        payload = {"tool_name": "Write", "tool_input": {"file_path": path, "content": text}}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                           text=True, env=dict(os.environ, IDENTIFIER_TERMS_FILE=str(self.terms), **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_this_repos_hooks_agents_and_commands_are_guarded(self):
        for path in ("/x/.agents/hooks/new.py", "/x/.agents/agents/helper.md", "/x/.agents/commands/run.md"):
            self.assertIn("a project alias", self.run_hook(path, f"about {TERM}"), path)

    def test_research_folders_are_guarded_under_both_names(self):
        for path in ("/x/.agents/_RESEARCH/notes.md", "/x/vault/RESEARCH/brief.md"):
            self.assertIn("a project alias", self.run_hook(path, f"about {TERM}"), path)

    def test_working_state_stays_unguarded(self):
        self.assertEqual(self.run_hook("/x/.agents/tasks/plan.md", f"about {TERM}"), "")

    def test_shapes_come_from_the_engine(self):
        out = self.run_hook("/x/.agents/skills/s/SKILL.md", "owner AB (" + "PM1) on STORY-" + "583920")
        self.assertIn("a person's initials with a role code", out)
        self.assertIn("a work-item identifier", out)
        self.assertNotIn("583920", out)

    def test_missing_engine_stays_silent(self):
        out = self.run_hook("/x/.agents/skills/s/SKILL.md", f"about {TERM}",
                            SANITIZE_SCRIPTS="/nonexistent/sanitize/scripts")
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()

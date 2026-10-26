#!/usr/bin/env python3
"""Tests for hooks/_shell_dirs.py, the shell-command folder walk shared by warn_cross_repo_git.py and
warn_foreign_edits.py.
Target: the repo's hooks/_shell_dirs.py by default; HOOK_UNDER_TEST points the run at a station copy.
Run: python3 tests/station-hooks/test-shell-dirs.py

Contract: walk(command, cwd) yields (words, folder) for every simple command, with leading prefixes
(sudo, env, rtk, assignments) stripped and `cd` moving the folder for the segments after it;
git_target(words, folder) returns the folder a git call acts on and the index of its subcommand.
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path

TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "_shell_dirs.py")
_spec = importlib.util.spec_from_file_location("_shell_dirs", TARGET)
sd = importlib.util.module_from_spec(_spec)
sys.modules["_shell_dirs"] = sd
_spec.loader.exec_module(sd)


class TestWalk(unittest.TestCase):
    def test_each_segment_gets_the_folder_it_runs_in(self):
        got = list(sd.walk("ls && cd sub ; make test | tee log", "/r"))
        self.assertEqual(got, [(["ls"], "/r"), (["make", "test"], "/r/sub"), (["tee", "log"], "/r/sub")])

    def test_prefixes_and_assignments_are_stripped(self):
        got = list(sd.walk("FOO=1 sudo rtk git status", "/r"))
        self.assertEqual(got, [(["git", "status"], "/r")])

    def test_cd_without_argument_goes_home_and_tilde_expands(self):
        self.assertEqual(list(sd.walk("cd && ls", "/r")), [(["ls"], str(Path.home()))])
        self.assertEqual(list(sd.walk("cd ~/x && ls", "/r")), [(["ls"], os.path.join(str(Path.home()), "x"))])

    def test_unbalanced_quotes_skip_the_segment(self):
        self.assertEqual(list(sd.walk("echo 'oops && ls", "/r")), [(["ls"], "/r")])

    def test_empty_command_yields_nothing(self):
        self.assertEqual(list(sd.walk("", "/r")), [])


class TestGitTarget(unittest.TestCase):
    def check(self, command, folder, sub):
        words = command.split()
        where, i = sd.git_target(words, "/r")
        self.assertEqual((os.path.normpath(where), words[i] if i < len(words) else None), (folder, sub))

    def test_plain_call_acts_on_its_folder(self):
        self.check("git commit -m x", "/r", "commit")

    def test_dash_c_chains_relative_to_the_last(self):
        self.check("git -C a -C b push", "/r/a/b", "push")

    def test_work_tree_and_git_dir(self):
        self.check("git --work-tree=w status", "/r/w", "status")
        self.check("git --git-dir=g/.git log", "/r/g", "log")
        self.check("git --git-dir g/.git log", "/r/g", "log")

    def test_dash_lowercase_c_value_is_skipped(self):
        self.check("git -c core.x=1 commit", "/r", "commit")


if __name__ == "__main__":
    unittest.main()

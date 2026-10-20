#!/usr/bin/env python3
"""Tests for the guard_git_bypass.py PreToolUse hook.
Target: the repo's hooks/guard_git_bypass.py by default; HOOK_UNDER_TEST points the run at a
station copy such as ~/.claude/hooks/guard_git_bypass.py.
Run: python3 tests/station-hooks/test-guard-git-bypass.py

Contract: exit 2 with the reason on stderr when an agent's command bypasses the station's git
hooks; exit 0 for everything else, including commands that only mention the same strings.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "guard_git_bypass.py")


def run(command, tool="Bash"):
    payload = {"hook_event_name": "PreToolUse", "prompt_id": "p", "tool_name": tool,
               "tool_input": {"command": command}, "cwd": "/tmp"}
    env = dict(os.environ, CLAUDE_PROJECT_DIR="/tmp")
    r = subprocess.run([sys.executable, str(TARGET)], input=json.dumps(payload), env=env,
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stderr


class TestRefused(unittest.TestCase):
    def assertRefused(self, command, what):
        code, err = run(command)
        self.assertEqual(code, 2, f"{command!r}: {err}")
        self.assertIn(what, err)
        self.assertIn("ask the user", err)

    def test_commit_no_verify_forms(self):
        for cmd in ('git commit --no-verify -m "x"', 'git commit -n -m "x"', 'git commit -an -m x',
                    'cd repo && git commit -qn -m x', 'git -C some/repo commit --no-verify'):
            self.assertRefused(cmd, "git commit --no-verify")

    def test_push_no_verify(self):
        self.assertRefused("git push --no-verify origin develop", "git push --no-verify")

    def test_hooks_path_overrides(self):
        self.assertRefused("git -c core.hooksPath=/dev/null commit -m x", "core.hooksPath override")
        self.assertRefused("git -c CORE.HOOKSPATH= push", "core.hooksPath override")
        self.assertRefused("git --config-env=core.hooksPath=X commit -m x", "core.hooksPath override")

    def test_git_config_env_overrides(self):
        what = "XDG_CONFIG_HOME override"
        self.assertRefused("GIT_CONFIG_GLOBAL=/dev/null git commit -m x", what)
        self.assertRefused("env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git push", what)
        self.assertRefused("export GIT_CONFIG_GLOBAL=/dev/null; git commit -m x", what)
        # each of these makes git skip the global config, and with it the hooks path
        self.assertRefused("HOME=/tmp git commit -m x", what)
        self.assertRefused("XDG_CONFIG_HOME=/tmp/x git push origin main", what)

    def test_abbreviated_no_verify(self):
        self.assertRefused("git commit --no-verif -m x", "git commit --no-verify")
        self.assertRefused("git push --no-veri origin main", "git push --no-verify")
        self.assertRefused("git merge --no-verify side", "git merge --no-verify")

    def test_include_path_and_shell_grammar(self):
        self.assertRefused("git -c include.path=/tmp/x commit -m x", "core.hooksPath override")
        for cmd in ("{ git commit -n -m x; }", "! git commit -n -m x", "if git commit -n -m x; then :; fi",
                    "exec git commit --no-verify", "sleep 1 & git commit -n -m x", "(git commit -n -m x)"):
            self.assertRefused(cmd, "git commit --no-verify")

    def test_a_separator_inside_a_quoted_message_does_not_hide_the_flag(self):
        self.assertRefused('git commit -m "a; b" --no-verify', "git commit --no-verify")
        self.assertRefused('git commit -m "fix a & b" --no-verify', "git commit --no-verify")
        self.assertRefused('git commit -m "x | y" -n', "git commit --no-verify")
        self.assertRefused("echo start\ngit commit -n -m x", "git commit --no-verify")
        self.assertRefused("case x in *) git commit -n -m x;; esac", "git commit --no-verify")

    def test_env_clearing_drops_the_global_config(self):
        what = "XDG_CONFIG_HOME override"
        self.assertRefused("env -i git commit -m x", what)
        self.assertRefused("env -u HOME git commit -m x", what)
        self.assertRefused("env --unset=XDG_CONFIG_HOME git push", what)

    def test_uninstalling_the_station_hooks(self):
        self.assertRefused("sh ~/.agents/hooks/git/install.sh --uninstall", "station hooks path")
        self.assertRefused("sh hooks/git/install.sh --force", "station hooks path")

    def test_config_writes(self):
        self.assertRefused("git config --global core.hooksPath /tmp/h", "core.hooksPath change")
        self.assertRefused("git config --unset core.hookspath", "core.hooksPath change")

    def test_wrappers_are_unwrapped(self):
        for cmd in ("sudo -u me git commit --no-verify", "nice -n 5 git commit -n -m x",
                    "time git push --no-verify", "echo x | xargs git commit --no-verify"):
            code, _ = run(cmd)
            self.assertEqual(code, 2, cmd)


class TestAllowed(unittest.TestCase):
    def assertAllowed(self, command, tool="Bash"):
        code, err = run(command, tool)
        self.assertEqual(code, 0, f"{command!r}: {err}")

    def test_ordinary_git(self):
        for cmd in ('git commit -m "fix"', 'git commit -am "x"', "git push origin develop",
                    "git push -n origin develop", "git status", "git log --oneline -3"):
            self.assertAllowed(cmd)

    def test_a_message_that_looks_like_a_flag(self):
        self.assertAllowed('git commit -m "-n is the dry run flag"')
        self.assertAllowed("git commit -mn")

    def test_optional_value_flags_are_not_read_as_n(self):
        self.assertAllowed("git commit -uno -m x")
        self.assertAllowed("git commit -Sabcn123 -m x")
        self.assertAllowed("sh ~/.agents/hooks/git/install.sh --check")
        self.assertAllowed("git status 2>&1")
        self.assertAllowed("git log --oneline &> /dev/null")

    def test_quoted_mentions_and_lookalike_names_pass(self):
        self.assertAllowed("echo 'x; git commit -n'")
        self.assertAllowed("HOMEBREW_NO_AUTO_UPDATE=1 git commit -m x")
        self.assertAllowed("env -u FOO git commit -m x")

    def test_mentions_are_not_calls(self):
        for cmd in ('grep -rn "no-verify" .', 'echo "git commit --no-verify"',
                    "python3 sanitize.py copy src --no-verify --out x",
                    "git log --grep=no-verify"):
            self.assertAllowed(cmd)

    def test_config_reads(self):
        self.assertAllowed("git config --global --get core.hooksPath")
        self.assertAllowed("git config --list --show-origin")

    def test_config_env_on_other_commands(self):
        self.assertAllowed("GIT_CONFIG_GLOBAL=/dev/null git status")

    def test_other_tools_and_garbage(self):
        self.assertAllowed("git commit --no-verify", tool="Read")
        r = subprocess.run([sys.executable, str(TARGET)], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()

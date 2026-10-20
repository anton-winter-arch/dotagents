#!/usr/bin/env python3
"""Tests for skills/task/scripts/task.py, the dispatcher in front of the harness scripts.

The dispatcher only routes, so these tests drive it end to end through its CLI and check
which harness script answered. No harness binary runs: `--help` and missing-report errors
are the harness scripts' own answers. Each harness suite lives under harnesses/<h>/tests.
Run: python3 -m unittest discover -s skills/task/tests -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "task.py"
STATE_VARS = {"codex": "CODEX_TASK_STATE", "cursor": "CURSOR_TASK_STATE",
              "antigravity": "ANTIGRAVITY_TASK_STATE"}


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        # The harness scripts refuse a state folder under /tmp or the user's temp tree,
        # so the per-test state lives under ~/.cache and is removed in tearDown.
        cache = Path.home() / ".cache"
        cache.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="task-dispatch-test-", dir=cache))
        self.state = {h: self.root / h for h in STATE_VARS}
        for p in self.state.values():
            p.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if k not in STATE_VARS.values() and k != "XDG_STATE_HOME"}
        self.env.update({STATE_VARS[h]: str(p) for h, p in self.state.items()})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def task(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def make_run(self, harness: str, run_id: str) -> Path:
        d = self.state[harness] / run_id
        d.mkdir()
        return d

    # usage

    def test_no_arguments_prints_usage_and_exits_2(self):
        r = self.task()
        self.assertEqual(r.returncode, 2)
        self.assertIn("task.py run <harness>", r.stdout)

    def test_help_exits_0(self):
        r = self.task("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("codex, cursor, antigravity", r.stdout)

    def test_unknown_command(self):
        r = self.task("launch", "codex")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown command 'launch'", r.stderr)

    def test_run_needs_a_harness(self):
        r = self.task("run")
        self.assertEqual(r.returncode, 2)
        self.assertIn("run needs a harness first", r.stderr)

    def test_run_unknown_harness(self):
        r = self.task("run", "copilot", "--repo", ".")
        self.assertEqual(r.returncode, 2)
        self.assertIn("got 'copilot'", r.stderr)

    # run

    def test_run_passes_flags_to_each_harness_script(self):
        for harness, marker in (("codex", "codex_task.py"), ("cursor", "cursor_task.py"),
                                ("antigravity", "antigravity_task.py")):
            with self.subTest(harness=harness):
                r = self.task("run", harness, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(marker, r.stdout)
                self.assertIn("--allow", r.stdout)

    # tryout

    def test_tryout_routes_to_the_bench(self):
        r = self.task("tryout", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("harness_bench.py", r.stdout)
        r = self.task("tryout", "tasks")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("fix-defect", r.stdout)

    # apply

    def test_apply_needs_a_run_id(self):
        r = self.task("apply")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs --run", r.stderr)

    def test_apply_rejects_a_path_as_run_id(self):
        for bad in ("../x", "a/b", ".hidden", ""):
            with self.subTest(run_id=bad):
                r = self.task("apply", "--run", bad)
                self.assertEqual(r.returncode, 2)
                self.assertIn("not a run id", r.stderr)

    def test_apply_rejects_a_trailing_newline_in_the_run_id(self):
        self.make_run("codex", "abc")
        r = self.task("apply", "--run", "abc\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a run id", r.stderr)

    def test_apply_refuses_a_repeated_run(self):
        self.make_run("codex", "one")
        self.make_run("cursor", "two")
        r = self.task("apply", "--run", "one", "--run=two")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--run given more than once", r.stderr)

    def test_apply_unknown_run_id(self):
        r = self.task("apply", "--run", "20991231-000000-none")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no harness has a run", r.stderr)

    def test_apply_routes_to_the_harness_that_owns_the_run(self):
        for harness in STATE_VARS:
            with self.subTest(harness=harness):
                run_id = f"route-{harness}"
                d = self.make_run(harness, run_id)
                r = self.task("apply", f"--run={run_id}")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(f"no report at {d.resolve() / 'report.json'}", r.stderr)

    def test_apply_ambiguous_run_id_names_both_harnesses(self):
        self.make_run("codex", "same-id")
        self.make_run("cursor", "same-id")
        r = self.task("apply", "--run", "same-id")
        self.assertEqual(r.returncode, 2)
        self.assertIn("exists for codex and cursor", r.stderr)

    def test_apply_with_a_named_harness_skips_the_lookup(self):
        self.make_run("codex", "same-id")
        d = self.make_run("cursor", "same-id")
        r = self.task("apply", "cursor", "--run", "same-id")
        self.assertIn(f"no report at {d.resolve() / 'report.json'}", r.stderr)

    # clean

    def test_clean_without_a_harness_cleans_every_harness(self):
        r = self.task("clean", "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        for harness in STATE_VARS:
            self.assertIn(f"== {harness}", r.stdout)

    def test_clean_with_a_run_id_routes_to_its_owner(self):
        d = self.make_run("antigravity", "clean-me")
        r = self.task("clean", "--run", "clean-me")
        # The harness's clean reads the run's report, so a bare folder is its own error,
        # and the error naming that folder proves the owner answered and nobody else ran.
        self.assertIn(f"antigravity-task: no report at {d.resolve() / 'report.json'}", r.stderr)
        self.assertNotIn("== codex", r.stdout)


FAKE_CODEX = HERE.parent / "harnesses" / "codex" / "tests" / "fake_codex.py"


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=True)


class SkillPreloadTest(unittest.TestCase):
    """--skill end to end through the Codex harness with its fake binary: the run's own
    rendered brief.md is the evidence of what the harness was given."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="task-skill-test-"))
        self.repo = self.tmp / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "allowed.py").write_text("def f():\n    return 1\n")
        git(["init", "-q", "-b", "main"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"], self.repo)
        self.brief = self.tmp / "brief.md"
        self.brief.write_text("Make f return 2.\n")
        self.skills = self.tmp / "skills"
        for name, body in (("demo", "DEMO-SKILL-MARKER\nAsk with the AskUserQuestion tool first.\n"),
                           ("plain", "PLAIN-SKILL-MARKER\n")):
            (self.skills / name).mkdir(parents=True)
            (self.skills / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n{body}")
        self.state = self.tmp / "state"
        self.xdg = self.tmp / "xdg"
        real_home = self.tmp / "real-codex-home"
        real_home.mkdir()
        (real_home / "auth.json").write_text('{"fake": true}')
        (real_home / "config.toml").write_text('model = "x"\n')
        self.env = dict(os.environ, TASK_TEST="1", TASK_SKILLS_ROOT=str(self.skills),
                        XDG_STATE_HOME=str(self.xdg), CODEX_TASK_TEST="1",
                        CODEX_TASK_BIN=str(FAKE_CODEX), CODEX_TASK_STATE=str(self.state),
                        CODEX_TASK_REAL_HOME=str(real_home), TMPDIR="/nonexistent-tmpdir-for-tests",
                        FAKE_CODEX_ARGV=str(self.tmp / "argv.json"), FAKE_CODEX_MODE="clean")

    def tearDown(self):
        for d in self.state.glob("*/ws"):
            subprocess.run(["git", "worktree", "remove", "--force", str(d)], cwd=str(self.repo),
                           capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def task(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env, input=stdin,
                              capture_output=True, text=True, timeout=60)

    def run_codex(self, *extra: str, brief: str | None = None, stdin: str | None = None):
        # The fake's clean mode edits allowed.py and creates new_allowed.py.
        return self.task("run", "codex", "--repo", str(self.repo), "--allow", "src/allowed.py",
                         "--allow", "src/new_allowed.py", "--brief", brief or str(self.brief),
                         *extra, stdin=stdin)

    def rendered_brief(self) -> str:
        runs = [p for p in self.state.iterdir() if p.is_dir() and p.name != "home"]
        self.assertEqual(len(runs), 1, runs)
        return (runs[0] / "brief.md").read_text()

    def test_skill_is_appended_to_the_brief_the_harness_renders(self):
        r = self.run_codex("--skill", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = self.rendered_brief()
        self.assertIn("Make f return 2.", brief)
        self.assertIn("## Skill to follow: demo", brief)
        self.assertIn("DEMO-SKILL-MARKER", brief)
        self.assertIn(str(self.skills / "demo"), brief)

    def test_skill_reaches_cursor_and_antigravity(self):
        tests = HERE.parent / "harnesses"
        # These two refuse a state folder inside the user's temp tree, as their own suites do.
        cache_state = Path.home() / ".cache" / f"task-skill-test-{self.tmp.name}"
        agent_home = self.tmp / "dot-gemini" / "antigravity-cli"
        agent_home.mkdir(parents=True)
        (agent_home / "settings.json").write_text('{"permissions": {"allow": ["write_file(*)"]}}')
        (self.tmp / "dot-cursor").mkdir()
        envs = {
            "cursor": {"CURSOR_TASK_TEST": "1", "CURSOR_TASK_BIN": str(tests / "cursor/tests/fake_agent.py"),
                       "CURSOR_TASK_SANDBOX_BIN": str(tests / "cursor/tests/fake_sandbox.py"),
                       "CURSOR_TASK_STATE": str(cache_state / "cursor"),
                       "CURSOR_TASK_CURSOR_HOME": str(self.tmp / "dot-cursor"),
                       "FAKE_AGENT_ARGV": str(self.tmp / "cursor-argv.json"), "FAKE_AGENT_MODE": "clean",
                       "FAKE_SANDBOX_RECORD": str(self.tmp / "cursor.sb")},
            "antigravity": {"ANTIGRAVITY_TASK_TEST": "1",
                            "ANTIGRAVITY_TASK_BIN": str(tests / "antigravity/tests/fake_agy.py"),
                            "ANTIGRAVITY_TASK_SANDBOX_BIN": str(tests / "antigravity/tests/fake_sandbox.py"),
                            "ANTIGRAVITY_TASK_STATE": str(cache_state / "antigravity"),
                            "ANTIGRAVITY_TASK_AGENT_HOME": str(self.tmp / "dot-gemini"),
                            "FAKE_AGY_ARGV": str(self.tmp / "agy-argv.json"), "FAKE_AGY_MODE": "clean",
                            "FAKE_SANDBOX_RECORD": str(self.tmp / "agy.sb")},
        }
        try:
            for harness, extra in envs.items():
                with self.subTest(harness=harness):
                    self.env.update(extra)
                    r = self.task("run", harness, "--repo", str(self.repo), "--allow", "src/allowed.py",
                                  "--allow", "src/new_allowed.py", "--brief", str(self.brief),
                                  "--skill", "plain")
                    self.assertEqual(r.returncode, 0, r.stderr)
                    state = Path(extra[f"{harness.upper()}_TASK_STATE"])
                    runs = [p for p in state.iterdir() if p.is_dir()]
                    self.assertEqual(len(runs), 1, runs)
                    rendered = (runs[0] / "brief.md").read_text()
                    self.assertIn("Make f return 2.", rendered)
                    self.assertIn("PLAIN-SKILL-MARKER", rendered)
        finally:
            for ws in cache_state.glob("*/*/ws"):
                subprocess.run(["git", "worktree", "remove", "--force", str(ws)], cwd=str(self.repo),
                               capture_output=True)
            shutil.rmtree(cache_state, ignore_errors=True)

    def test_claude_only_tools_warn(self):
        r = self.run_codex("--skill", "demo")
        self.assertIn("warning: skill 'demo' names Claude Code-only tools (AskUserQuestion)", r.stderr)
        r2 = self.task("run", "codex", "--help")  # a run without --skill never warns
        self.assertNotIn("warning", r2.stderr)

    def test_repeated_skills_are_added_once_each_in_order(self):
        r = self.run_codex("--skill", "plain", "--skill=demo", "--skill", "plain")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = self.rendered_brief()
        self.assertEqual(brief.count("PLAIN-SKILL-MARKER"), 1)
        self.assertLess(brief.index("PLAIN-SKILL-MARKER"), brief.index("DEMO-SKILL-MARKER"))
        self.assertNotIn("warning: skill 'plain'", r.stderr)

    def test_brief_from_stdin(self):
        r = self.run_codex("--skill", "plain", brief="-", stdin="From stdin.\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = self.rendered_brief()
        self.assertIn("From stdin.", brief)
        self.assertIn("PLAIN-SKILL-MARKER", brief)

    def test_combined_brief_is_private_and_old_ones_are_pruned(self):
        out = self.xdg / "task" / "briefs"
        out.mkdir(parents=True)
        old = out / "brief-old.md"
        old.write_text("stale")
        two_days_ago = time.time() - 2 * 86400
        os.utime(old, (two_days_ago, two_days_ago))
        r = self.run_codex("--skill", "plain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(old.exists())
        written = list(out.glob("brief-*.md"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].stat().st_mode & 0o777, 0o600)

    def test_briefs_folder_that_is_a_link_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (self.xdg / "task").mkdir(parents=True)
        (self.xdg / "task" / "briefs").symlink_to(elsewhere, target_is_directory=True)
        r = self.run_codex("--skill", "plain")
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not a real folder", r.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_briefs_folder_open_to_others_is_tightened(self):
        out = self.xdg / "task" / "briefs"
        out.mkdir(parents=True)
        out.chmod(0o777)
        r = self.run_codex("--skill", "plain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(out.stat().st_mode & 0o777, 0o700)

    def test_prune_skips_links_and_folders(self):
        out = self.xdg / "task" / "briefs"
        out.mkdir(parents=True)
        (out / "brief-dangling.md").symlink_to(self.tmp / "missing")
        (out / "brief-folder.md").mkdir()
        r = self.run_codex("--skill", "plain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / "brief-folder.md").is_dir())

    def test_bad_skill_names_exit_2_before_the_harness_runs(self):
        for name, message in (("missing", "no skill 'missing'"), ("../x", "not a skill name"),
                              ("Demo", "not a skill name"), ("task", "cannot preload itself")):
            with self.subTest(name=name):
                r = self.run_codex("--skill", name)
                self.assertEqual(r.returncode, 2)
                self.assertIn(message, r.stderr)
        self.assertFalse(self.state.exists() and any(p.name != "home" for p in self.state.iterdir()))

    def test_skill_folder_symlinked_outside_the_root_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text("OUTSIDE\n")
        (self.skills / "escape").symlink_to(outside, target_is_directory=True)
        r = self.run_codex("--skill", "escape")
        self.assertEqual(r.returncode, 2)
        self.assertIn("resolves outside", r.stderr)

    def test_skill_needs_a_readable_brief(self):
        r = self.task("run", "codex", "--repo", str(self.repo), "--skill", "plain")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs exactly one --brief", r.stderr)
        r = self.run_codex("--skill", "plain", brief=str(self.tmp / "nope.md"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot read the brief", r.stderr)

    def test_skills_root_override_needs_the_test_opt_in(self):
        env = dict(self.env)
        env.pop("TASK_TEST")
        r = subprocess.run([sys.executable, str(SCRIPT), "run", "codex", "--repo", str(self.repo),
                            "--allow", "src/allowed.py", "--brief", str(self.brief), "--skill", "demo"],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no skill 'demo' under", r.stderr)
        self.assertNotIn(str(self.skills), r.stderr)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for skills/skill-authoring/scripts/trigger_ab.py.

A fake `claude` on PATH stands in for the model: it reads the skill's SKILL.md as the run
left it, decides from its description and the query whether to call the skill, logs what
it saw, and spends nothing. A temporary git repo holds the skill at its old and new
description.
Run: python3 -m unittest discover -s skills/skill-authoring/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "trigger_ab.py"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
query = sys.stdin.read()
model = args[args.index("--model") + 1]
desc = Path(os.environ["FAKE_SKILL_MD"]).read_text()
new = "NEW" in desc
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"model": model, "cwd_is_git": Path(".git").is_dir()}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", os.environ["FAKE_TOKEN"]])
    time.sleep(float(os.environ["FAKE_SLEEP"]))
def out(e): print(json.dumps(e), flush=True)
out({"type": "system", "subtype": "init", "model": model})
fire = "steady" in query or (("REGRESS" in query or "GAIN" in query) and not new)
tool = {"type": "tool_use", "name": "Skill" if fire else "Agent",
        "input": {"skill": "demo"} if fire else {"prompt": "x"}}
out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [tool]}})
out({"type": "result", "is_error": False})
'''


def git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def skill_md(desc: str) -> str:
    return f"---\nname: demo\ndescription: {desc}\n---\n\n# demo\n"


class DescriptionParserTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import trigger_ab
        self.parse = trigger_ab.description_of

    def test_scalar_forms(self):
        self.assertEqual(self.parse("---\nname: a\ndescription: Plain words.\n---\nbody\n"), "Plain words.")
        self.assertEqual(self.parse("---\ndescription: \"Quoted words.\"\n---\n"), "Quoted words.")

    def test_folded_block_joins_its_lines(self):
        text = "---\nname: a\ndescription: >-\n  First line\n  second line.\nlicense: MIT\n---\n"
        self.assertEqual(self.parse(text), "First line second line.")

    def test_missing_description_or_frontmatter_is_none(self):
        self.assertIsNone(self.parse("---\nname: a\n---\ndescription: in the body\n"))
        self.assertIsNone(self.parse("no frontmatter\ndescription: x\n"))

    def test_unclosed_frontmatter_is_none(self):
        self.assertIsNone(self.parse("---\nname: a\ndescription: body-no-close\n"))


class TriggerABTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="trigger-ab-test-"))
        self.repo = self.tmp / "repo"
        skill = self.repo / "skills" / "demo"
        (skill / "evals").mkdir(parents=True)
        (skill / "SKILL.md").write_text(skill_md("OLD wording. Use when asked."))
        (skill / "evals" / "triggers.json").write_text(json.dumps([
            {"query": "steady case", "should_trigger": True},
            {"query": "REGRESS case", "should_trigger": True},
            {"query": "GAIN case", "should_trigger": False},
        ]))
        git(["init", "-q", "-b", "main"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"], self.repo)
        self.links = self.tmp / "station-skills"
        self.links.mkdir(parents=True)
        (self.links / "demo").symlink_to(skill, target_is_directory=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "fake.log"
        self.env = dict(os.environ, TRIGGER_AB_TEST="1", TRIGGER_AB_LINK_DIR=str(self.links),
                        FAKE_LOG=str(self.log), XDG_STATE_HOME=str(self.tmp / "state"),
                        FAKE_SKILL_MD=str(skill / "SKILL.md"),
                        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ab(self, *args: str, env=None, skill="demo") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), skill, "--root", str(self.repo), *args],
                              env=env or self.env, capture_output=True, text=True, timeout=120)

    def change_description(self):
        (self.repo / "skills" / "demo" / "SKILL.md").write_text(skill_md("NEW wording. Use when asked."))

    def test_unchanged_description_is_skipped_and_spends_nothing(self):
        r = self.ab()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("description unchanged since HEAD; skipped", r.stdout)
        self.assertFalse(self.log.exists())

    def test_dry_run_prints_the_call_count(self):
        self.change_description()
        r = self.ab("--dry-run", "--runs", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 skill(s), 18 probe calls on claude-sonnet-5-5", r.stdout)
        self.assertFalse(self.log.exists())

    def test_regression_and_gain_are_reported_and_a_regression_exits_1(self):
        self.change_description()
        r = self.ab()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("## demo: old 2/3, new 2/3", r.stdout)
        self.assertIn("- REGRESSION (should fire, old 1/1, new 0/1): REGRESS case", r.stdout)
        self.assertIn("- gain (should not fire, old 1/1, new 0/1): GAIN case", r.stdout)
        saved = list((self.tmp / "state" / "skill-authoring" / "trigger-ab").glob("*/demo.json"))
        self.assertEqual(len(saved), 1)

    def test_probes_run_in_a_git_project_with_the_pinned_model(self):
        self.change_description()
        self.ab()
        runs = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(runs), 6)
        for run in runs:
            self.assertEqual(run["model"], "claude-sonnet-5-5")
            self.assertTrue(run["cwd_is_git"])

    def test_the_working_tree_skill_file_is_restored(self):
        self.change_description()
        md = self.repo / "skills" / "demo" / "SKILL.md"
        before = md.read_bytes()
        self.ab()
        self.assertEqual(md.read_bytes(), before)

    def test_a_stand_in_left_by_an_older_run_is_restored_at_start(self):
        original = os.readlink(self.links / "demo")
        (self.links / "demo").unlink()
        stand_in = self.links / "demo"
        stand_in.mkdir()
        (stand_in / ".trigger-ab-hidden").write_text(original)
        (stand_in / "evals").symlink_to(self.repo / "skills" / "demo" / "evals")
        r = self.ab()
        self.assertIn("restored", r.stdout)
        self.assertTrue((self.links / "demo").is_symlink())
        self.assertEqual(os.readlink(self.links / "demo"), original)

    def test_names_and_refs_that_could_escape_are_refused(self):
        self.change_description()
        r = self.ab(skill="../demo")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a skill name", r.stderr)
        r = self.ab("--base-ref=--output=/tmp/x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a git ref", r.stderr)
        self.assertFalse(self.log.exists())

    def test_old_runner_flags_are_still_accepted(self):
        r = self.ab("--jobs", "4", "--skill-creator", "/x", "--variant-timeout", "9")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_hung_probe_stops_at_its_timeout_with_no_survivor(self):
        import signal
        import time
        import uuid
        self.change_description()
        token = f"trigger-ab-test-{uuid.uuid4().hex}"

        def tokened():
            out = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True,
                                 timeout=10).stdout
            return [int(line.split()[0]) for line in out.splitlines() if token in line]
        started = time.monotonic()
        try:
            r = self.ab("--timeout", "2", env=dict(self.env, FAKE_SLEEP="60", FAKE_TOKEN=token))
            self.assertLess(time.monotonic() - started, 45, "the run waited out hung probes")
            self.assertEqual(r.returncode, 0, r.stderr)   # every probe missed, so old and new agree
            time.sleep(0.5)
            self.assertEqual(tokened(), [], "a tokened probe outlived the run")
        finally:
            for pid in tokened():
                os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for skills/skill-authoring/scripts/trigger_ab.py.

A fake skill-creator plugin stands in for run_eval.py: it scores cases from the
description it is handed, records the folder it ran in and what the skill's station
link looked like mid-run, and spends nothing. A temporary git repo holds the skill at
its old and new description.
Run: python3 -m unittest discover -s skills/skill-authoring/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "trigger_ab.py"

FAKE_RUN_EVAL = r'''
import argparse, json, os, sys
from pathlib import Path
p = argparse.ArgumentParser()
for flag in ("--eval-set", "--skill-path", "--description", "--num-workers", "--runs-per-query",
             "--timeout", "--model"):
    p.add_argument(flag)
a = p.parse_args()
cwd = Path.cwd()
if not (cwd / ".claude").is_dir() or cwd == Path.home():
    sys.exit(3)
link = Path(os.environ["TRIGGER_AB_LINK_DIR"]) / Path(a.skill_path).name
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"link_is_symlink": link.is_symlink(),
                          "skill_md": (link / "SKILL.md").exists(),
                          "scripts": (link / "scripts" / "tool.py").exists(),
                          "workers": a.num_workers, "model": a.model}) + "\n")
if os.environ.get("FAKE_SLEEP"):
    with open(os.environ["FAKE_PIDS"], "a") as pids:
        pids.write(f"{os.getpid()}\n")
    import time
    time.sleep(float(os.environ["FAKE_SLEEP"]))
new = "NEW" in a.description
results = []
for c in json.loads(Path(a.eval_set).read_text()):
    ok = not (("REGRESS" in c["query"] and new) or ("GAIN" in c["query"] and not new))
    trig = int(ok) if c["should_trigger"] else int(not ok)
    results.append({"query": c["query"], "should_trigger": c["should_trigger"],
                    "triggers": trig, "runs": 1, "pass": ok})
print("progress line before the JSON")
print(json.dumps({"results": results, "summary": {"passed": sum(r["pass"] for r in results),
                                                  "failed": 0, "total": len(results)}}))
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
        (skill / "scripts").mkdir()
        (skill / "scripts" / "tool.py").write_text("# a script a hook would load\n")
        (skill / "SKILL.md").write_text(skill_md("OLD wording. Use when asked."))
        (skill / "evals" / "triggers.json").write_text(json.dumps([
            {"query": "steady case", "should_trigger": True},
            {"query": "REGRESS case", "should_trigger": True},
            {"query": "GAIN case", "should_trigger": False},
        ]))
        git(["init", "-q", "-b", "main"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], self.repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"], self.repo)
        self.creator = self.tmp / "skill-creator"
        (self.creator / "scripts").mkdir(parents=True)
        (self.creator / "scripts" / "__init__.py").write_text("")
        (self.creator / "scripts" / "run_eval.py").write_text(FAKE_RUN_EVAL)
        self.links = self.tmp / "station-skills"
        self.links.mkdir()
        (self.links / "demo").symlink_to(skill, target_is_directory=True)
        self.log = self.tmp / "fake.log"
        self.env = dict(os.environ, TRIGGER_AB_TEST="1", TRIGGER_AB_LINK_DIR=str(self.links),
                        FAKE_LOG=str(self.log), XDG_STATE_HOME=str(self.tmp / "state"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ab(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "demo", "--root", str(self.repo),
                               "--skill-creator", str(self.creator), *args],
                              env=self.env, capture_output=True, text=True, timeout=120)

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
        self.assertIn("1 skill(s), 18 probe calls on claude-sonnet-5", r.stdout)
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

    def test_each_variant_runs_in_its_own_project_with_one_worker_and_the_pinned_model(self):
        self.change_description()
        self.ab()
        runs = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(runs), 2)
        for run in runs:
            self.assertEqual(run["workers"], "1")
            self.assertEqual(run["model"], "claude-sonnet-5")

    def test_skill_is_hidden_without_breaking_its_scripts_then_the_link_returns(self):
        self.change_description()
        original = os.readlink(self.links / "demo")
        self.ab()
        for run in (json.loads(line) for line in self.log.read_text().splitlines()):
            self.assertFalse(run["link_is_symlink"])
            self.assertFalse(run["skill_md"])
            self.assertTrue(run["scripts"])
        self.assertTrue((self.links / "demo").is_symlink())
        self.assertEqual(os.readlink(self.links / "demo"), original)

    def test_a_stand_in_left_by_a_killed_run_is_restored_at_start(self):
        original = os.readlink(self.links / "demo")
        (self.links / "demo").unlink()
        stand_in = self.links / "demo"
        stand_in.mkdir()
        (stand_in / ".trigger-ab-hidden").write_text(original)
        (stand_in / "scripts").symlink_to(self.repo / "skills" / "demo" / "scripts")
        r = self.ab()
        self.assertIn("restored", r.stdout)
        self.assertTrue((self.links / "demo").is_symlink())
        self.assertEqual(os.readlink(self.links / "demo"), original)

    def test_names_and_refs_that_could_escape_are_refused(self):
        self.change_description()
        r = subprocess.run([sys.executable, str(SCRIPT), "../demo", "--root", str(self.repo),
                            "--skill-creator", str(self.creator)], env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a skill name", r.stderr)
        # argparse refuses `--base-ref --output=...` on its own; the `=` form reaches the check.
        r = self.ab("--base-ref=--output=/tmp/x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a git ref", r.stderr)
        self.assertFalse(self.log.exists())

    def test_a_second_run_waits_its_turn_instead_of_touching_the_first(self):
        self.change_description()
        lock_dir = self.tmp / "state" / "skill-authoring" / "trigger-ab"
        lock_dir.mkdir(parents=True)
        with open(lock_dir / "lock", "w") as held:
            import fcntl
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.ab()
        self.assertEqual(r.returncode, 2)
        self.assertIn("another trigger_ab run is active", r.stderr)
        self.assertTrue((self.links / "demo").is_symlink())
        self.assertFalse(self.log.exists())

    def test_sigterm_mid_run_restores_the_link_and_stops_the_runner(self):
        import signal
        import time
        self.change_description()
        original = os.readlink(self.links / "demo")
        pids = self.tmp / "pids"
        env = dict(self.env, FAKE_SLEEP="30", FAKE_PIDS=str(pids))
        p = subprocess.Popen([sys.executable, str(SCRIPT), "demo", "--root", str(self.repo),
                              "--skill-creator", str(self.creator)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 20
        while time.time() < deadline and not (pids.exists() and len(pids.read_text().split()) == 2):
            time.sleep(0.1)
        self.assertFalse((self.links / "demo").is_symlink(), "the skill should be hidden mid-run")
        p.send_signal(signal.SIGTERM)
        _, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 128 + signal.SIGTERM, err)
        self.assertIn("hidden skills restored", err)
        self.assertTrue((self.links / "demo").is_symlink())
        self.assertEqual(os.readlink(self.links / "demo"), original)
        time.sleep(0.5)
        for pid in map(int, pids.read_text().split()):
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_a_real_folder_at_the_station_path_is_refused(self):
        self.change_description()
        (self.links / "demo").unlink()
        (self.links / "demo").mkdir()
        (self.links / "demo" / "SKILL.md").write_text("a real local skill")
        r = self.ab()
        self.assertEqual(r.returncode, 2)
        self.assertIn("is a real folder, not a link", r.stderr)
        self.assertEqual((self.links / "demo" / "SKILL.md").read_text(), "a real local skill")


if __name__ == "__main__":
    unittest.main()

"""Tests for scripts/trigger_eval.py.

    python3 -m unittest discover -s tests

No test spends a model call: scoring runs on recorded event shapes, and the
end-to-end tests put a fake `claude` on PATH.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import trigger_eval as te  # noqa: E402

MODEL = "claude-sonnet-5-5"


def init(model=MODEL):
    return {"type": "system", "subtype": "init", "model": model}


def call(name, parent=None, **inp):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def text(words="done", parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "text", "text": words}]}}


def score(events, target="goldfish", cap=8):
    return te.score(events, target, cap)


class TestScore(unittest.TestCase):
    def test_skill_call_after_exploration_is_a_hit(self):
        got = score([init(), call("Bash", command="ls"), call("Read", file_path="/p/tasks/x.md"),
                     call("Skill", skill="goldfish", args="tasks/x.md")])
        self.assertEqual(got["verdict"], "hit")
        self.assertEqual(got["tools"], ["Bash", "Read", "Skill:goldfish"])

    def test_reading_the_skill_file_is_a_hit(self):
        got = score([init(), call("Read", file_path="/cfg/skills/goldfish/SKILL.md")])
        self.assertEqual(got["verdict"], "hit")

    def test_doing_the_work_first_is_a_miss(self):
        for tool in ("Agent", "Task", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            got = score([init(), call("Bash", command="ls"), call(tool, prompt="review it")])
            self.assertEqual((got["verdict"], got["reason"]), ("miss", f"did-the-work:{tool}"), tool)

    def test_a_sibling_skill_is_a_miss_that_names_the_sibling(self):
        got = score([init(), call("Skill", skill="code-review")])
        self.assertEqual((got["verdict"], got["reason"]), ("miss", "sibling:code-review"))

    def test_a_subagent_calling_the_skill_does_not_count(self):
        got = score([init(), call("Bash", command="ls"),
                     call("Skill", parent="toolu_1", skill="goldfish"),
                     call("Write", file_path="/p/out.md")])
        self.assertEqual((got["verdict"], got["reason"]), ("miss", "did-the-work:Write"))
        self.assertNotIn("Skill:goldfish", got["tools"])

    def test_answering_without_a_tool_is_a_miss(self):
        got = score([init(), text("Here is my review.")])
        self.assertEqual((got["verdict"], got["reason"]), ("miss", "answered"))

    def test_exploring_past_the_cap_is_a_miss(self):
        got = score([init()] + [call("Bash", command="ls")] * 3, cap=3)
        self.assertEqual((got["verdict"], got["reason"]), ("miss", "cap"))

    def test_events_after_the_decision_are_ignored(self):
        got = score([init(), call("Skill", skill="goldfish"), call("Write", file_path="/p/x")])
        self.assertEqual(got["verdict"], "hit")

    def test_a_different_model_is_refused(self):
        with self.assertRaises(te.EvalError):
            score([init("claude-haiku-5-5"), call("Skill", skill="goldfish")])

    def test_a_logged_out_claude_is_refused(self):
        with self.assertRaises(te.EvalError):
            te.Scorer("goldfish", 8, MODEL).feed_line("Not logged in · Please run /login")


class SkillCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="te-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.skill = self.tmp / "goldfish"
        (self.skill / "evals" / "fixture").mkdir(parents=True)
        self.md_text = "---\nname: goldfish\ndescription: >-\n  Old text\n  for goldfish.\n---\n\n# body\n"
        (self.skill / "SKILL.md").write_text(self.md_text)
        (self.skill / "evals" / "fixture" / "notes.md").write_text("ok\n")


class TestFixture(SkillCase):
    def test_a_plain_fixture_seeds_a_git_project(self):
        project = te.new_project(self.skill)
        self.addCleanup(shutil.rmtree, project, True)
        self.assertTrue((project / ".git").is_dir())
        self.assertEqual((project / "notes.md").read_text(), "ok\n")

    def test_config_and_links_in_a_fixture_are_refused(self):
        fixture = self.skill / "evals" / "fixture"
        for make in (lambda: (fixture / ".claude").mkdir(),
                     lambda: (fixture / ".Claude").mkdir(),
                     lambda: (fixture / ".mcp.json").write_text("{}"),
                     lambda: (fixture / "creds").symlink_to(self.tmp / "secret")):
            make()
            with self.assertRaises(te.EvalError):
                te.new_project(self.skill)
            for p in (fixture / ".claude", fixture / ".Claude", fixture / ".mcp.json", fixture / "creds"):
                if p.is_symlink() or p.is_file():
                    p.unlink()
                elif p.is_dir():
                    p.rmdir()


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
query = sys.stdin.read()
model = args[args.index("--model") + 1]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"query": query, "cwd_is_git": os.path.isdir(".git"),
                          "skill_md": open(os.environ["FAKE_SKILL_MD"]).read(),
                          "api_key": "ANTHROPIC_API_KEY" in os.environ,
                          "auth_token": "ANTHROPIC_AUTH_TOKEN" in os.environ}) + "\n")
def out(e): print(json.dumps(e), flush=True)
out({"type": "system", "subtype": "init", "model": os.environ.get("FAKE_MODEL", model)})
out({"type": "assistant", "parent_tool_use_id": None,
     "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})
if "goldfish" in query:
    tool = {"type": "tool_use", "name": "Skill", "input": {"skill": "goldfish"}}
else:
    tool = {"type": "tool_use", "name": "Agent", "input": {"prompt": "x"}}
out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [tool]}})
out({"type": "result", "is_error": False})
'''


class TestEndToEnd(SkillCase):
    def setUp(self):
        super().setUp()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        (self.skill / "evals" / "triggers.json").write_text(json.dumps([
            {"query": "goldfish the x spec", "should_trigger": True},
            {"query": "review my diff", "should_trigger": False},
            {"query": "-x is the x spec ready to build", "should_trigger": True}]))
        self.log = self.tmp / "fake.log"
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                        FAKE_LOG=str(self.log), FAKE_SKILL_MD=str(self.skill / "SKILL.md"),
                        XDG_STATE_HOME=str(self.tmp / "state"),
                        ANTHROPIC_API_KEY="k", ANTHROPIC_AUTH_TOKEN="t")

    def run_cli(self, *extra, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "trigger_eval.py"), str(self.skill), "--runs", "2",
             "--model", MODEL, *extra],
            capture_output=True, text=True, env=env or self.env, timeout=60)

    def logged(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_results_have_run_eval_shape_and_score_each_case(self):
        p = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        rows = {r["query"]: r for r in data["results"]}
        self.assertEqual(rows["goldfish the x spec"]["triggers"], 2)
        self.assertTrue(rows["goldfish the x spec"]["pass"])
        self.assertTrue(rows["review my diff"]["pass"])
        self.assertFalse(rows["-x is the x spec ready to build"]["pass"])
        self.assertEqual(rows["-x is the x spec ready to build"]["detail"][0]["reason"],
                         "did-the-work:Agent")
        self.assertEqual(data["summary"], {"total": 3, "passed": 2, "failed": 1})

    def test_probes_get_the_case_on_stdin_in_a_git_project_without_api_keys(self):
        self.run_cli()
        rows = self.logged()
        self.assertIn("-x is the x spec ready to build", [r["query"] for r in rows])
        for row in rows:
            self.assertTrue(row["cwd_is_git"])
            self.assertFalse(row["api_key"] or row["auth_token"])

    def test_a_description_is_tested_in_place_and_the_file_restored(self):
        p = self.run_cli("--description", "New text: here.")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["description"], "New text: here.")
        for row in self.logged():
            self.assertEqual(te.description_of(row["skill_md"]), "New text: here.")
        self.assertEqual((self.skill / "SKILL.md").read_text(), self.md_text)

    def test_the_file_is_restored_when_the_run_fails(self):
        p = self.run_cli("--description", "New.", env=dict(self.env, FAKE_MODEL="claude-haiku-5-5"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("model", p.stderr)
        self.assertEqual((self.skill / "SKILL.md").read_text(), self.md_text)

    def test_a_backup_left_by_a_killed_run_is_restored_first(self):
        state = self.tmp / "state" / "skill-authoring" / "trigger-eval"
        state.mkdir(parents=True)
        (state / "goldfish.SKILL.md.orig").write_text(self.md_text)
        (self.skill / "SKILL.md").write_text(self.md_text.replace("Old text", "Variant"))
        p = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.skill / "SKILL.md").read_text(), self.md_text)
        self.assertFalse((state / "goldfish.SKILL.md.orig").exists())

    def test_a_linked_skill_md_is_refused(self):
        real = self.tmp / "elsewhere.md"
        real.write_text(self.md_text)
        (self.skill / "SKILL.md").unlink()
        (self.skill / "SKILL.md").symlink_to(real)
        p = self.run_cli("--description", "New.")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(real.read_text(), self.md_text)

    def test_the_results_feed_trigger_ab_compare(self):
        import trigger_ab
        data = json.loads(self.run_cli().stdout)
        c = trigger_ab.compare(data, data)
        self.assertEqual((c["total"], c["regressions"]), (3, []))


if __name__ == "__main__":
    unittest.main()

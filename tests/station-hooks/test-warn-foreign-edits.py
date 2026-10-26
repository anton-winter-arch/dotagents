#!/usr/bin/env python3
"""Tests for the warn_foreign_edits.py hook (tasks/SPEC-FOREIGN-EDIT-WARNING.md).
Target: the repo's hooks/warn_foreign_edits.py by default; HOOK_UNDER_TEST points the run at a station copy.
Run: python3 tests/station-hooks/test-warn-foreign-edits.py

Contract: advisory only, exit 0 on every path. A change to a git working tree that lands between two of
this session's own tool calls is foreign and is reported at the session's next write or shell call;
changes made inside the session's own calls, its subagents' calls and its own parallel file-write
batches are not. record mode logs instead of speaking, off does nothing.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "warn_foreign_edits.py")
FIXTURE = Path(__file__).resolve().parents[2] / "hooks" / "tests" / "fixtures" / "claude-code-foreign-edit.json"


def load_module():
    spec = importlib.util.spec_from_file_location("warn_foreign_edits", TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["warn_foreign_edits"] = mod
    spec.loader.exec_module(mod)
    return mod


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    (path / "README.md").write_text("seed\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "seed")
    return Path(os.path.realpath(path))


class Session:
    """Drives the hook the way Claude Code does for one session."""

    def __init__(self, test, sid, home, mode="warn", extra_env=None):
        self.t, self.sid, self.home, self.n = test, sid, home, 0
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("FOREIGN_EDIT_")}
        self.env.update({"FOREIGN_EDIT_STATE_DIR": str(test.state), "FOREIGN_EDIT_MODE": mode,
                         "CLAUDE_PROJECT_DIR": str(home), "CLAUDECODE": "1"})
        self.env.update(extra_env or {})

    def send(self, event, **fields):
        payload = {"hook_event_name": event, "session_id": self.sid, "cwd": str(self.home),
                   "transcript_path": "/tmp/t.jsonl", "permission_mode": "default", **fields}
        r = subprocess.run([sys.executable, str(TARGET)], input=json.dumps(payload), capture_output=True,
                           text=True, env=self.env, timeout=30)
        self.t.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def new_id(self):
        self.n += 1
        return f"toolu_{self.sid}_{self.n:04d}"

    def pre(self, tool, agent=None, **ti):
        tid = self.new_id()
        extra = {"agent_id": agent, "agent_type": "general-purpose"} if agent else {}
        return tid, self.send("PreToolUse", tool_name=tool, tool_use_id=tid, tool_input=ti, **extra)

    def post(self, tool, tid, agent=None, failed=False, **ti):
        extra = {"agent_id": agent} if agent else {}
        return self.send("PostToolUseFailure" if failed else "PostToolUse", tool_name=tool, tool_use_id=tid,
                         tool_input=ti, **extra)

    def batch(self, agent=None):
        extra = {"agent_id": agent} if agent else {}
        return self.send("PostToolBatch", tool_calls=[], **extra)

    def write(self, path: Path, text: str):
        """This session's own Write call, effect included; returns the PreToolUse output."""
        tid, out = self.pre("Write", file_path=str(path), content=text)
        path.write_text(text)
        self.post("Write", tid, file_path=str(path), content=text)
        self.batch()
        return out

    def shell(self, command: str, effect=None, background=False):
        ti = {"command": command}
        if background:
            ti["run_in_background"] = True
        tid, out = self.pre("Bash", **ti)
        if effect:
            effect()
        self.post("Bash", tid, **ti)
        self.batch()
        return out


def text(out):
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


class TestForeignEdits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="foreign-edit-test-"))
        self.state = self.tmp / "state"
        self.repo = init_repo(self.tmp / "repo")
        self.me = Session(self, "me", self.repo)
        self.assertIsNone(self.me.send("SessionStart", source="startup"))

    def log_lines(self):
        log = self.state / "log.jsonl"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    # -- foreign changes are reported ---------------------------------------------------------------

    def test_change_between_calls_is_reported_at_the_next_write(self):
        self.assertIsNone(self.me.write(self.repo / "a.txt", "mine"))
        (self.repo / "b.txt").write_text("theirs")
        out = self.me.write(self.repo / "c.txt", "mine")
        self.assertIn("b.txt", text(out))
        self.assertNotIn("a.txt", text(out))
        self.assertIn("not by this session", text(out))
        self.assertIn("systemMessage", out)

    def test_outside_commit_reports_the_head_move_and_its_paths(self):
        self.me.write(self.repo / "a.txt", "mine")
        (self.repo / "skill.md").write_text("theirs")
        git(self.repo, "add", "skill.md")
        git(self.repo, "commit", "-q", "-m", "outside")
        out = self.me.shell("git status")
        self.assertIn("HEAD moved", text(out))
        self.assertIn("skill.md", text(out))

    def test_old_change_is_reported_with_idle_wording(self):
        self.me.write(self.repo / "a.txt", "mine")
        old = self.repo / "old.txt"
        old.write_text("theirs")
        hour_ago = time.time() - 3600
        os.utime(old, (hour_ago, hour_ago))
        out = self.me.write(self.repo / "c.txt", "mine")
        self.assertIn("old.txt", text(out))
        self.assertIn("while this session was idle", text(out))

    def test_held_work_is_reported_once_at_session_start(self):
        (self.repo / "left.txt").write_text("uncommitted")
        other = Session(self, "late", self.repo)
        out = other.send("SessionStart", source="startup")
        self.assertIn("left.txt", text(out))
        self.assertIn("not made by this session", text(out))
        self.assertIsNone(other.send("SessionStart", source="resume"))
        self.assertIsNone(other.write(self.repo / "z.txt", "mine"))

    def test_denied_call_does_not_wedge_the_in_flight_set(self):
        self.me.pre("Bash", command="touch denied.txt")
        self.me.batch()
        (self.repo / "b.txt").write_text("theirs")
        out = self.me.write(self.repo / "c.txt", "mine")
        self.assertIn("b.txt", text(out))

    def test_failed_call_clears_through_post_tool_use_failure(self):
        tid, _ = self.me.pre("Bash", command="false")
        self.me.post("Bash", tid, failed=True, command="false")
        (self.repo / "b.txt").write_text("theirs")
        tid2, out = self.me.pre("Bash", command="ls")
        self.assertIn("b.txt", text(out))

    def test_change_during_a_file_write_batch_is_foreign(self):
        t1, _ = self.me.pre("Write", file_path=str(self.repo / "p1.txt"), content="1")
        t2, _ = self.me.pre("Write", file_path=str(self.repo / "p2.txt"), content="2")
        (self.repo / "p1.txt").write_text("1")
        (self.repo / "intruder.txt").write_text("theirs")
        (self.repo / "p2.txt").write_text("2")
        self.me.post("Write", t1, file_path=str(self.repo / "p1.txt"))
        self.me.post("Write", t2, file_path=str(self.repo / "p2.txt"))
        self.me.batch()
        out = self.me.write(self.repo / "c.txt", "mine")
        self.assertIn("intruder.txt", text(out))
        self.assertNotIn("p1.txt", text(out))

    def test_incident_replay_second_session_edits_and_commits_a_skill(self):
        peer = Session(self, "peer", self.repo)
        peer.send("SessionStart", source="startup")
        self.me.write(self.repo / "mine.txt", "mine")
        skill = self.repo / "skills" / "vault"
        skill.mkdir(parents=True)
        self.assertIn("mine.txt", text(peer.write(skill / "SKILL.md", "theirs")))  # each side sees the other
        out = self.me.shell("git add -A")
        self.assertIn("skills/vault/SKILL.md", text(out))
        peer.shell("git commit", effect=lambda: (git(self.repo, "add", "skills"), git(self.repo, "commit", "-q", "-m", "peer")))
        out = self.me.write(self.repo / "mine2.txt", "mine")
        self.assertIn("HEAD moved", text(out))

    def test_second_repo_touched_by_shell_is_watched_too(self):
        other = init_repo(self.tmp / "other")
        self.assertIsNone(self.me.shell(f"cd {other} && make", effect=lambda: (other / "built.txt").write_text("x")))
        (other / "theirs.txt").write_text("theirs")
        out = self.me.shell(f"git -C {other} status")
        self.assertIn("theirs.txt", text(out))
        self.assertNotIn("built.txt", text(out))

    # -- this session's own work stays silent -------------------------------------------------------

    def test_own_writes_and_shell_effects_are_silent(self):
        self.assertIsNone(self.me.write(self.repo / "a.txt", "1"))
        self.assertIsNone(self.me.shell("sed -i '' s/1/2/ a.txt", effect=lambda: (self.repo / "a.txt").write_text("2")))
        self.assertIsNone(self.me.shell("python3 gen.py", effect=lambda: (self.repo / "gen.txt").write_text("g")))
        self.assertIsNone(self.me.shell("git add -A && git commit -m x",
                                        effect=lambda: (git(self.repo, "add", "-A"), git(self.repo, "commit", "-q", "-m", "x"))))
        self.assertIsNone(self.me.write(self.repo / "b.txt", "1"))

    def test_change_during_a_shell_batch_is_ambiguous_and_only_logged(self):
        t1, _ = self.me.pre("Bash", command="sleep 2")
        t2, _ = self.me.pre("Bash", command="sleep 3")
        (self.repo / "during.txt").write_text("who?")
        self.me.post("Bash", t1, command="sleep 2")
        self.me.post("Bash", t2, command="sleep 3")
        self.me.batch()
        self.assertIsNone(self.me.write(self.repo / "c.txt", "mine"))
        self.assertIn("ambiguous", [l["signal"] for l in self.log_lines()])

    def test_subagent_calls_are_the_sessions_own(self):
        tid, _ = self.me.pre("Write", agent="sub1", file_path=str(self.repo / "e.txt"), content="sub")
        (self.repo / "e.txt").write_text("sub")
        self.me.post("Write", tid, agent="sub1", file_path=str(self.repo / "e.txt"))
        self.me.batch(agent="sub1")
        self.me.send("SubagentStop", agent_id="sub1")
        self.assertIsNone(self.me.write(self.repo / "c.txt", "mine"))

    def test_main_batch_leaves_a_subagent_call_in_flight(self):
        self.me.pre("Bash", agent="sub1", command="long job")
        self.me.batch()
        (self.repo / "during.txt").write_text("who?")
        self.assertIsNone(self.me.write(self.repo / "c.txt", "mine"))
        self.me.send("SubagentStop", agent_id="sub1")

    def test_read_only_tools_never_check(self):
        (self.repo / "b.txt").write_text("theirs")
        self.assertIsNone(self.me.send("PreToolUse", tool_name="Read", tool_use_id="r1",
                                       tool_input={"file_path": str(self.repo / "b.txt")}))

    # -- noise control ------------------------------------------------------------------------------

    def test_same_foreign_set_is_reported_once_and_resaves_are_capped(self):
        f = self.repo / "busy.txt"
        f.write_text("1")
        self.assertIn("busy.txt", text(self.me.write(self.repo / "a.txt", "x")))
        self.assertIsNone(self.me.write(self.repo / "b.txt", "x"))
        f.write_text("2")
        later = time.time() + 5
        os.utime(f, (later, later))
        self.assertIsNone(self.me.write(self.repo / "c.txt", "x"))
        loud = Session(self, "me", self.repo, extra_env={"FOREIGN_EDIT_REREPORT_S": "0"})
        f.write_text("3")
        evenlater = time.time() + 10
        os.utime(f, (evenlater, evenlater))
        self.assertIn("busy.txt", text(loud.write(self.repo / "d.txt", "x")))

    def test_warning_stays_one_short_line_however_many_files(self):
        self.me.write(self.repo / "a.txt", "x")
        for i in range(12):
            (self.repo / f"a-rather-long-folder-name-{i:02d}").mkdir()
            (self.repo / f"a-rather-long-folder-name-{i:02d}" / "with-a-long-file-name.md").write_text("theirs")
        msg = text(self.me.write(self.repo / "c.txt", "x"))
        self.assertIn("+10 more", msg)
        self.assertEqual(msg.count("\n"), 0)
        self.assertLess(len(msg), 220, msg)

    def test_background_launch_labels_later_changes(self):
        self.me.shell("sleep 6 && make", background=True)
        (self.repo / "late.txt").write_text("bg?")
        out = self.me.write(self.repo / "c.txt", "mine")
        self.assertIn("background command", text(out))
        self.assertLess(len(text(out)), 220)

    def test_stale_in_flight_entry_expires(self):
        self.me.pre("Bash", command="hung")
        (self.repo / "b.txt").write_text("theirs")
        quick = Session(self, "me", self.repo, extra_env={"FOREIGN_EDIT_INFLIGHT_TTL_S": "0"})
        _, out = quick.pre("Write", file_path=str(self.repo / "c.txt"), content="x")
        self.assertIn("b.txt", text(out))

    def test_user_prompt_clears_the_main_agents_entries(self):
        self.me.pre("Bash", command="interrupted")
        self.me.send("UserPromptSubmit", prompt="go on")
        (self.repo / "b.txt").write_text("theirs")
        self.assertIn("b.txt", text(self.me.write(self.repo / "c.txt", "mine")))

    def test_stop_clears_the_main_agents_entries(self):
        self.me.pre("Bash", command="interrupted")
        self.me.send("Stop", background_tasks=[])
        (self.repo / "b.txt").write_text("theirs")
        self.assertIn("b.txt", text(self.me.write(self.repo / "c.txt", "mine")))

    def test_linked_worktree_is_its_own_tree(self):
        wt = Path(os.path.realpath(self.tmp)) / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "side", str(wt))
        self.me.write(wt / "mine.txt", "x")
        (self.repo / "main-only.txt").write_text("theirs")
        (wt / "theirs.txt").write_text("theirs")
        msg = text(self.me.write(wt / "mine2.txt", "x"))
        self.assertIn("theirs.txt", msg)
        self.assertIn("/wt", msg)
        self.assertNotIn("main-only.txt", msg.split("\n")[[i for i, l in enumerate(msg.split("\n")) if "/wt" in l][0]])

    def test_parallel_hook_calls_do_not_lose_state(self):
        ids = [f"toolu_par_{i}" for i in range(8)]

        def burst(event):
            procs = [subprocess.Popen([sys.executable, str(TARGET)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, env=self.me.env) for _ in ids]
            for p, tid in zip(procs, ids):
                p.stdin.write(json.dumps({"hook_event_name": event, "session_id": "me", "cwd": str(self.repo),
                                          "tool_name": "Bash", "tool_use_id": tid, "tool_input": {"command": "ls"}}))
                p.stdin.close()
            for p in procs:
                self.assertEqual(p.wait(timeout=60), 0)

        burst("PreToolUse")
        state = json.loads((self.state / "sessions" / "me.json").read_text())
        self.assertEqual(sorted(state["inflight"]), sorted(ids))
        burst("PostToolUse")
        state = json.loads((self.state / "sessions" / "me.json").read_text())
        self.assertEqual(state["inflight"], {})

    # -- modes and robustness -----------------------------------------------------------------------

    def test_record_mode_logs_without_speaking(self):
        rec = Session(self, "rec", self.repo, mode="record")
        rec.send("SessionStart", source="startup")
        rec.write(self.repo / "a.txt", "x")
        (self.repo / "b.txt").write_text("theirs")
        self.assertIsNone(rec.write(self.repo / "c.txt", "x"))
        live = [l for l in self.log_lines() if l["session"] == "rec" and l["signal"] == "live"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["paths"], ["b.txt"])
        self.assertIsInstance(live[0]["ages_s"][0], (int, float))
        self.assertNotIn("theirs", (self.state / "log.jsonl").read_text())

    def test_off_mode_does_nothing(self):
        off = Session(self, "off", self.repo, mode="off")
        (self.repo / "b.txt").write_text("theirs")
        self.assertIsNone(off.send("SessionStart", source="startup"))
        self.assertIsNone(off.write(self.repo / "c.txt", "x"))
        self.assertFalse((self.state / "sessions" / "off.json").exists())

    def test_git_timeout_is_silent_and_backs_off(self):
        self.me.write(self.repo / "a.txt", "x")
        (self.repo / "b.txt").write_text("theirs")
        slow = Session(self, "me", self.repo, extra_env={"FOREIGN_EDIT_GIT_TIMEOUT_S": "0.000001"})
        self.assertIsNone(slow.write(self.repo / "c.txt", "x"))
        self.assertIn("timeout", [l["signal"] for l in self.log_lines()])
        self.assertIsNone(self.me.write(self.repo / "d.txt", "x"))  # backing off: no checks, no false report
        after = Session(self, "me", self.repo, extra_env={"FOREIGN_EDIT_BACKOFF_S": "0"})
        self.assertIsNone(after.write(self.repo / "e.txt", "x"))  # the back-off ends with a silent new baseline
        (self.repo / "f.txt").write_text("theirs")
        self.assertIn("f.txt", text(after.write(self.repo / "g.txt", "x")))
        self.assertNotIn("e.txt", text(after.write(self.repo / "h.txt", "x")))

    def test_repo_with_a_local_filter_command_is_never_scanned(self):
        risky = init_repo(self.tmp / "risky")
        marker = self.tmp / "MARKER"
        (risky / ".gitattributes").write_text("*.txt filter=x\n")
        git(risky, "config", "filter.x.clean", f"touch {marker}; cat")
        (risky / "a.txt").write_text("a\n")
        git(risky, "add", ".gitattributes", "a.txt")
        git(risky, "commit", "-q", "-m", "filtered")
        marker.unlink()
        later = time.time() + 5
        os.utime(risky / "a.txt", (later, later))
        s = Session(self, "risky", risky)
        self.assertIsNone(s.send("SessionStart", source="startup"))
        (risky / "theirs.txt").write_text("x")
        self.assertIsNone(s.write(risky / "c.txt", "x"))
        self.assertFalse(marker.exists(), "the hook ran the repo's filter command")
        self.assertIn("unsafe-config", [l["signal"] for l in self.log_lines()])

    def test_pruning_removes_a_stale_session_with_its_lock_and_keeps_live_ones(self):
        sessions = self.state / "sessions"
        old = time.time() - 8 * 86400
        (sessions / "gone.json").write_text("{}")
        (sessions / "gone.lock").write_text("")
        os.utime(sessions / "gone.json", (old, old))
        os.utime(sessions / "me.lock", (old, old))
        Session(self, "fresh", self.repo).send("SessionStart", source="startup")
        self.assertFalse((sessions / "gone.json").exists())
        self.assertFalse((sessions / "gone.lock").exists())
        self.assertTrue((sessions / "me.lock").exists())

    def test_garbage_input_exits_zero_silently(self):
        r = subprocess.run([sys.executable, str(TARGET)], input="not json", capture_output=True, text=True,
                           env={**self.me.env})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_outside_git_is_silent(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        s = Session(self, "plain", plain)
        self.assertIsNone(s.send("SessionStart", source="startup"))
        self.assertIsNone(s.write(plain / "x.txt", "x"))

    def test_captured_session_replays_silently(self):
        events = json.loads(FIXTURE.read_text())["denied_subagent_and_batches"]
        s = Session(self, "replay", self.repo)
        for e in events:
            e = json.loads(json.dumps(e).replace("/tmp/fe-capture/repo", str(self.repo)))
            fields = {k: v for k, v in e.items() if k not in ("hook_event_name", "session_id", "offset_s")}
            out = s.send(e["hook_event_name"], **fields)
            self.assertEqual(text(out), "", e)
            ti = e.get("tool_input") or {}
            if e["hook_event_name"] == "PreToolUse" and e.get("tool_name") == "Write":
                Path(ti["file_path"]).write_text("x")


class TestUnits(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def test_parse_status_reads_head_branch_and_every_entry_kind(self):
        raw = ("# branch.oid abc123\0# branch.head main\0"
               "1 .M N... 100644 100644 100644 h1 h2 changed.txt\0"
               "2 R. N... 100644 100644 100644 h1 h2 R100 new name.txt\0old name.txt\0"
               "u UU N... 100644 100644 100644 100644 h1 h2 h3 conflict.txt\0"
               "? untracked dir/file.txt\0").encode()
        head, ref, paths = self.m.parse_status(raw)
        self.assertEqual((head, ref), ("abc123", "main"))
        self.assertEqual(sorted(paths), ["changed.txt", "conflict.txt", "new name.txt", "untracked dir/file.txt"])
        self.assertEqual(paths["new name.txt"], "R.")

    def test_diff_reports_added_changed_and_cleaned_paths(self):
        old = {"head": "a", "ref": "main", "files": {"x": [".M", 1.0, 3], "gone": ["??", 1.0, 1]}}
        new = {"head": "a", "ref": "main", "files": {"x": [".M", 2.0, 3], "y": ["??", 5.0, 1]}}
        changes, head = self.m.diff(old, new)
        self.assertEqual(sorted(c["path"] for c in changes), ["gone", "x", "y"])
        self.assertIsNone(head)

    def test_diff_reports_a_head_move(self):
        old = {"head": "a", "ref": "main", "files": {}}
        new = {"head": "b", "ref": "main", "files": {}}
        self.assertEqual(self.m.diff(old, new)[1], {"from": "a", "to": "b", "ref_from": "main", "ref_to": "main"})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for the session web state (_web_guard.py), the fetch-tool hook (web_fetch_guard.py)
and the session-end hook (web_session_end.py).
Target: the repo's hooks/ by default; HOOKS_UNDER_TEST points the run at a station copy such
as ~/.claude/hooks.
Run: python3 tests/station-hooks/test-web-fetch-guard.py   (or via unittest discover)

Contract: a 401, 403, 429 or 503 blocks the host for the session and nothing clears it; a
blocked or capped host is `deny` for a subagent and `ask` for the main session; requests to
one host are spaced; sessions share nothing; the session-end hook removes only its folder.
No test sends a request anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOKS = Path(os.environ.get("HOOKS_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks")
FETCH, END, GUARD = HOOKS / "web_fetch_guard.py", HOOKS / "web_session_end.py", HOOKS / "_web_guard.py"

spec = importlib.util.spec_from_file_location("_web_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
sys.modules["_web_guard"] = guard
spec.loader.exec_module(guard)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, TMPDIR=self.tmp.name, WEB_GUARD_DELAY="0", WEB_GUARD_CAP="20")
        self.old = tempfile.tempdir
        tempfile.tempdir = self.tmp.name          # the in-process guard reads the same folder
        self.addCleanup(lambda: setattr(tempfile, "tempdir", self.old))

    def hook(self, script: Path, payload, **env):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run([sys.executable, str(script)], input=text, text=True, capture_output=True,
                           env=dict(self.env, **env))
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def pre(self, url, sid="s1", agent=False, **env):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "WebFetch", "session_id": sid,
                   "tool_input": {"url": url, "prompt": "p"}}
        if agent:
            payload.update(agent_id="a1", agent_type="researcher")
        return self.hook(FETCH, payload, **env)

    def post(self, url, code, sid="s1"):
        return self.hook(FETCH, {"hook_event_name": "PostToolUse", "tool_name": "WebFetch", "session_id": sid,
                                 "tool_input": {"url": url}, "tool_response": {"code": code, "url": url}})


class GuardModule(Base):
    def test_requests_to_one_host_are_spaced(self):
        os.environ["WEB_GUARD_DELAY"] = "2"
        self.addCleanup(os.environ.pop, "WEB_GUARD_DELAY", None)
        with guard.locked("s1") as st:
            waits = [guard.reserve(st, "a.example", now=100.0) for _ in range(3)]
            other = guard.reserve(st, "b.example", now=100.0)
        self.assertEqual(waits, [("ok", 0.0), ("ok", 2.0), ("ok", 4.0)])
        self.assertEqual(other, ("ok", 0.0))

    def test_cap(self):
        os.environ["WEB_GUARD_CAP"] = "2"
        self.addCleanup(os.environ.pop, "WEB_GUARD_CAP", None)
        with guard.locked("s1") as st:
            got = [guard.reserve(st, "a.example", now=1.0)[0] for _ in range(3)]
        self.assertEqual(got, ["ok", "ok", "cap"])

    def test_a_refusal_is_final_and_keeps_its_first_code(self):
        with guard.locked("s1") as st:
            guard.refuse(st, "a.example", 403)
            guard.refuse(st, "a.example", 429)
        with guard.locked("s1") as st:
            self.assertEqual(guard.reserve(st, "a.example"), ("blocked", 403.0))
        self.assertEqual(guard.blocked(guard.read("s1"), "a.example"), 403)

    def test_sessions_share_nothing(self):
        with guard.locked("s1") as st:
            guard.refuse(st, "a.example", 403)
        self.assertEqual(guard.blocked(guard.read("s2"), "a.example"), 0)

    def test_strict_hosts(self):
        for host in ("www.army.mil", "nasa.gov", "data.service.gov.uk", "gov.uk", "exercito.mil.br"):
            self.assertTrue(guard.is_strict(host), host)
        for host in ("governance.example.com", "mil.example.com", "gov.example.org", "example.com"):
            self.assertFalse(guard.is_strict(host), host)

    def test_session_id_cannot_shape_a_path(self):
        self.assertEqual(guard.session_id({"session_id": "../../x"}, {}), "")
        self.assertEqual(guard.session_id({"session_id": "abc-123"}, {}), "abc-123")
        self.assertEqual(guard.session_id({}, {"CLAUDE_CODE_SESSION_ID": "e-1"}), "e-1")

    def test_twenty_parallel_writers_leave_a_valid_count(self):
        code = ("import importlib.util,sys\n"
                "s=importlib.util.spec_from_file_location('_web_guard',sys.argv[1])\n"
                "g=importlib.util.module_from_spec(s); sys.modules['_web_guard']=g; s.loader.exec_module(g)\n"
                "with g.locked('par') as st: g.reserve(st,'a.example')\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(GUARD)], env=dict(self.env, WEB_GUARD_CAP="99"))
                 for _ in range(20)]
        for p in procs:
            self.assertEqual(p.wait(), 0)
        self.assertEqual(guard.read("par")["hosts"]["a.example"]["count"], 20)


class FetchHook(Base):
    def test_a_403_blocks_the_host_deny_for_a_subagent_ask_for_the_main_session(self):
        self.assertIsNone(self.pre("https://a.example/1"))
        self.post("https://a.example/1", 403)
        for n in range(8):
            out = self.pre("https://a.example/%d" % n, agent=True)
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("403", out["permissionDecisionReason"])
        self.assertEqual(self.pre("https://a.example/9")["permissionDecision"], "ask")
        self.assertEqual(self.pre("https://a.example/9")["permissionDecision"], "ask", "an approved ask clears nothing")
        self.assertIsNone(self.pre("https://b.example/1", agent=True), "another host is untouched")

    def test_other_statuses_and_shapes(self):
        self.post("https://ok.example/", 200)
        self.post("https://gone.example/", 404)
        self.assertIsNone(self.pre("https://ok.example/", agent=True))
        self.assertIsNone(self.pre("https://gone.example/", agent=True))
        self.hook(FETCH, {"hook_event_name": "PostToolUseFailure", "tool_name": "WebFetch", "session_id": "s1",
                          "tool_input": {"url": "https://busy.example/"},
                          "error": "Request failed with status code 429"})
        self.assertEqual(self.pre("https://busy.example/", agent=True)["permissionDecision"], "deny")
        self.hook(FETCH, {"hook_event_name": "PostToolUse", "tool_name": "WebFetch", "session_id": "s1",
                          "tool_input": {"url": "https://str.example/"},
                          "tool_response": json.dumps({"code": 503})})
        self.assertEqual(self.pre("https://str.example/", agent=True)["permissionDecision"], "deny")

    def test_page_text_that_mentions_a_status_blocks_nothing(self):
        self.hook(FETCH, {"hook_event_name": "PostToolUse", "tool_name": "WebFetch", "session_id": "s1",
                          "tool_input": {"url": "https://docs.example/"},
                          "tool_response": "This page explains status code 429 and status code 403."})
        self.hook(FETCH, {"hook_event_name": "PostToolUse", "tool_name": "WebFetch", "session_id": "s1",
                          "tool_input": {"url": "https://docs.example/"},
                          "tool_response": {"code": 200, "result": "Request failed with status code 403"}})
        self.assertIsNone(self.pre("https://docs.example/", agent=True))

    def test_government_and_military_hosts_ask_in_every_form(self):
        for url in ("https://www.example.gov/a", "https://data.example.gov.uk/a", "https://www.example.mil/a"):
            for agent, verdict in ((False, "ask"), (True, "deny")):
                out = self.pre(url, agent=agent)
                self.assertEqual(out["permissionDecision"], verdict, url)
                self.assertIn("government or military", out["permissionDecisionReason"])
        self.post("https://www.example.gov/a", 403)
        self.assertEqual(self.pre("https://www.example.gov/b", agent=True)["permissionDecision"], "deny")

    def test_the_government_rule_holds_without_a_session_or_usable_state(self):
        for sid in ("", "a.b", "../x"):
            self.assertEqual(self.pre("https://www.example.gov/a", sid=sid)["permissionDecision"], "ask", sid)
            self.assertEqual(self.pre("https://www.example.gov/a", sid=sid, agent=True)["permissionDecision"], "deny")
            self.assertIsNone(self.pre("https://example.org/a", sid=sid, agent=True))
        root = Path(self.tmp.name) / ("web-guard-%d" % os.getuid())
        root.mkdir(exist_ok=True)
        os.chmod(root, 0o755)
        self.assertEqual(self.pre("https://data.example.gov.uk/a", agent=True)["permissionDecision"], "deny")
        self.assertEqual(self.pre("https://data.example.gov.uk/a")["permissionDecision"], "ask")

    def test_a_refused_wait_gives_its_slot_back(self):
        self.assertIsNone(self.pre("https://q.example/1", WEB_GUARD_DELAY="60", WEB_GUARD_CAP="3"))
        for _ in range(5):
            self.assertIn("queued", self.pre("https://q.example/2", WEB_GUARD_DELAY="60", WEB_GUARD_CAP="3")
                          ["permissionDecisionReason"])
        entry = guard.read("s1")["hosts"]["q.example"]
        self.assertEqual(entry["count"], 1, "refused calls do not use up the cap")

    def test_a_state_folder_this_user_did_not_make_private_is_not_used(self):
        root = Path(self.tmp.name) / ("web-guard-%d" % os.getuid())
        (root / "s1").mkdir(parents=True)
        os.chmod(root, 0o777)
        self.post("https://a.example/", 403)
        self.assertFalse((root / "s1" / "state.json").exists())
        self.assertIsNone(self.pre("https://a.example/", agent=True), "fails open")

    def test_two_sessions_share_no_state_and_subagents_of_one_do(self):
        self.post("https://a.example/", 403, sid="s1")
        self.assertIsNone(self.pre("https://a.example/", sid="s2", agent=True))
        self.assertEqual(self.pre("https://a.example/", sid="s1", agent=True)["permissionDecision"], "deny")

    def test_requests_are_spaced_and_a_deep_queue_is_refused(self):
        self.assertIsNone(self.pre("https://a.example/1", WEB_GUARD_DELAY="0.5"))
        start = time.time()
        self.assertIsNone(self.pre("https://a.example/2", WEB_GUARD_DELAY="0.5"))
        self.assertGreaterEqual(time.time() - start, 0.3)
        self.assertIsNone(self.pre("https://q.example/1", WEB_GUARD_DELAY="60"))
        out = self.pre("https://q.example/2", WEB_GUARD_DELAY="60")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("queued", out["permissionDecisionReason"])

    def test_cap(self):
        for _ in range(2):
            self.assertIsNone(self.pre("https://a.example/", agent=True, WEB_GUARD_CAP="2"))
        self.assertEqual(self.pre("https://a.example/", agent=True, WEB_GUARD_CAP="2")["permissionDecision"], "deny")
        self.assertEqual(self.pre("https://a.example/", WEB_GUARD_CAP="2")["permissionDecision"], "ask")

    def test_loopback_is_not_tracked(self):
        self.post("http://127.0.0.1:8000/", 403)
        self.assertIsNone(self.pre("http://127.0.0.1:8000/", agent=True))
        self.assertFalse((Path(self.tmp.name) / ("web-guard-%d" % os.getuid()) / "s1" / "state.json").exists())

    def test_fails_open(self):
        for raw in ("not json", "[]", json.dumps({"hook_event_name": "PreToolUse"}),
                    json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"url": 5}, "session_id": "s1"}),
                    json.dumps({"hook_event_name": "PreToolUse", "tool_input": {"url": "https://a.example"},
                                "session_id": "../x"})):
            self.assertIsNone(self.hook(FETCH, raw))

    def test_a_large_payload_is_fast(self):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "WebFetch", "session_id": "s1",
                   "tool_input": {"url": "https://a.example/"},
                   "tool_response": {"code": 200, "result": "x" * 300_000}}
        start = time.time()
        self.hook(FETCH, payload)
        self.assertLess(time.time() - start, 2.0)


class SessionEnd(Base):
    def end(self, sid="s1", **env):
        return self.hook(END, {"hook_event_name": "SessionEnd", "session_id": sid}, **env)

    def test_removes_only_its_own_session_folder(self):
        self.post("https://a.example/", 403, sid="s1")
        self.post("https://a.example/", 403, sid="s2")
        keep = Path(self.tmp.name) / "unrelated.txt"
        keep.write_text("stay")
        root = Path(self.tmp.name) / ("web-guard-%d" % os.getuid())
        self.end("s1")
        self.assertFalse((root / "s1").exists())
        self.assertTrue((root / "s2" / "state.json").exists())
        self.assertTrue(keep.exists())

    def test_scans_recorded_download_folders_when_the_scanner_is_installed(self):
        batch = Path(self.tmp.name) / "batch"
        batch.mkdir()
        gone = Path(self.tmp.name) / "gone"
        with guard.locked("s1") as st:
            guard.note_download_dir(st, str(batch))
            guard.note_download_dir(st, str(gone))
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        record = Path(self.tmp.name) / "scan-args.txt"
        fake = bin_dir / "local-security"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"" + str(record) + "\"\n")
        fake.chmod(0o755)
        self.end("s1", PATH=str(bin_dir) + os.pathsep + self.env.get("PATH", ""))
        for _ in range(50):
            if record.exists() and record.read_text().strip():
                break
            time.sleep(0.1)
        self.assertEqual(record.read_text().split("\n")[:3], ["scan", "path", os.path.realpath(str(batch))])

    def test_crafted_download_folders_are_not_passed_to_the_scanner(self):
        batch = Path(self.tmp.name) / "batch"
        batch.mkdir()
        folder = Path(self.tmp.name) / ("web-guard-%d" % os.getuid()) / "s1"
        folder.mkdir(parents=True, mode=0o700)
        os.chmod(folder.parent, 0o700)
        (folder / "state.json").write_text(json.dumps({"hosts": {}, "download_dirs": [
            "-x", "--help", "relative/dir", "/tmp", os.path.expanduser("~"), 7, str(batch)]}))
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        record = Path(self.tmp.name) / "scan-args.txt"
        fake = bin_dir / "local-security"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"" + str(record) + "\"\n")
        fake.chmod(0o755)
        self.end("s1", PATH=str(bin_dir) + os.pathsep + self.env.get("PATH", ""))
        for _ in range(50):
            if record.exists() and record.read_text().strip():
                break
            time.sleep(0.1)
        self.assertEqual(record.read_text().split(), ["scan", "path", os.path.realpath(str(batch))])

    def test_no_state_no_action_and_fails_open(self):
        self.assertIsNone(self.end("never-used"))
        self.assertIsNone(self.hook(END, "not json"))
        self.assertIsNone(self.hook(END, {"hook_event_name": "SessionEnd", "session_id": "../x"}))


if __name__ == "__main__":
    unittest.main()

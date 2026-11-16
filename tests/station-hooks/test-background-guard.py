#!/usr/bin/env python3
"""Tests for the background_guard.py PreToolUse hook.
Target: the repo's hooks/background_guard.py by default; HOOK_UNDER_TEST points the run
at a station copy such as ~/.claude/hooks/background_guard.py.
Run: python3 tests/station-hooks/test-background-guard.py   (or via unittest discover)

Contract: a run_in_background command passes only as one procguard call with a timeout of
1 to 7200 seconds, after optional `cd` steps, not --detached, and not an interpreter reading
its program from stdin. Any command that detaches work (a lone `&`, nohup, setsid, disown)
exits 2. Quoted text, `&&`, `2>&1` and here-document bodies never count. Fails open.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "background_guard.py")
REPO = Path(__file__).resolve().parents[2]
# The guard accepts procguard by content, so the tests point at the copy beside the hook
# under test rather than at whatever this machine's station holds.
PG = f"python3 {TARGET.parent / 'procguard.py'}"
SKILL_COPY = REPO / "skills" / "skill-authoring" / "scripts" / "procguard.py"


def run(command: str, background: bool = False, tool: str = "Bash") -> subprocess.CompletedProcess:
    tool_input = {"command": command}
    if background:
        tool_input["run_in_background"] = True
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": "t", "tool_input": tool_input}
    return subprocess.run([sys.executable, str(TARGET)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=10)


class BackgroundCase(unittest.TestCase):
    ALLOWED = [
        f"{PG} --timeout 600 -- python3 /tmp/scratch/bench.py",
        f"cd /tmp/x && {PG} --timeout 7200 --grace 5 -- npm run build",
        f"/usr/bin/python3 {SKILL_COPY} --timeout 30 -- make test",
        f"{PG} --timeout 900 -- bash -c 'make serve & wait'",
        f"{PG} --timeout 60 -- bash -c 'echo $(date)'",                            # inside the guard
    ]
    BLOCKED = [
        "python3 /Users/someone/.claude/hooks/procguard.py --timeout 30 -- make test",   # no such file
        f"{PG} --timeout 60 --det --timeout 9999999 -- sleep 99999",                     # abbreviation, repeat
        f"{PG} --timeout 60 --timeout 9999999 -- sleep 99999",
        f"{PG} --timeout 60 --grace 9999999 -- sleep 99999",
        f"{PG} --timeout=60 -- sleep 99999",
        f"{PG} --timeout 60 -- setsid sleep 99999",
        f"{PG} --timeout 60 -- nohup sleep 99999",
        f'cd "$(sleep 99999; echo /tmp)" && {PG} --timeout 60 -- make',            # runs outside the guard
        f"{PG} --timeout 60 -- echo `sleep 99999`",
        "python3 -I - <<'EOF'\nimport time\ntime.sleep(99999)\nEOF",   # the Nov 14 command shape
        "python3 /tmp/bench.py",
        "sleep 1000",
        f"{PG} -- python3 x.py",
        f"{PG} --timeout 0 -- python3 x.py",
        f"{PG} --timeout 7201 -- python3 x.py",
        f"{PG} --timeout soon -- python3 x.py",
        f"{PG} --timeout 60 --detached -- python3 x.py",
        f"{PG} --timeout 60",
        f"{PG} --timeout 60 -- python3 - <<'EOF'\nprint(1)\nEOF",
        f"{PG} --timeout 60 -- python3 -I -",
        f"git status; {PG} --timeout 60 -- make",
        f"{PG} --timeout 10 -- sleep 1 > >(sleep 999)",                              # runs outside the guard
        f"cd /tmp;\nsleep 99999\n{PG} --timeout 10 -- true",                         # `;\n` is one token
        f"cd /tmp &&\nsleep 99999\n{PG} --timeout 10 -- true",
        f"cd {TARGET.parent} && python3 procguard.py --timeout 10 -- sleep 1",        # relative path
        f"{PG} --timeout 10 -- echo " + "x" * 33_000,                                 # too long to check
    ]

    def test_allowed(self):
        for cmd in self.ALLOWED:
            with self.subTest(cmd=cmd):
                p = run(cmd, background=True)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_blocked(self):
        for cmd in self.BLOCKED:
            with self.subTest(cmd=cmd):
                p = run(cmd, background=True)
                self.assertEqual(p.returncode, 2, cmd)
                self.assertIn("procguard.py", p.stderr)

    def test_a_different_file_named_procguard_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "procguard.py"
            fake.write_text("import os; os.execvp('sleep', ['sleep', '99999'])\n")
            p = run(f"python3 {fake} --timeout 60 -- sleep 1", background=True)
            self.assertEqual(p.returncode, 2)

    def test_foreground_commands_are_not_wrapped(self):
        for cmd in ("python3 /tmp/bench.py", "python3 - <<'EOF'\nprint(1)\nEOF", "make test"):
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd).returncode, 0)


class DetachCase(unittest.TestCase):
    BLOCKED = [
        "python3 server.py &",
        "python3 server.py & echo started",
        "nohup python3 server.py",
        "setsid python3 server.py",
        "python3 a.py & disown",
        "FOO=1 nohup ./run.sh > log 2>&1",
        "nohup sleep 99999 & echo $'a\\'b'",       # bash quoting shlex cannot parse
        'bash -c "sleep 99999 &"',
        "sh -c 'setsid sleep 99999'",
        "(sleep 1000 &)",
        "sleep 1000 &;echo x",
    ]
    ALLOWED = [
        "make && make test",
        "make 2>&1 | tee build.log",
        "make |& tee build.log",
        "cmd > out.log 2>&1",
        "cmd &> out.log",
        "echo 'a & b'",
        'git commit -m "fix: x & y; nohup in text"',
        "grep -n 'nohup' file.sh",
        "cat <<'EOF' > notes.txt\nrun it with nohup &\nEOF",
        "curl -s 'https://example.com/?a=1&b=2'",
    ]

    def test_blocked_foreground_and_background(self):
        for cmd in self.BLOCKED:
            for bg in (False, True):
                with self.subTest(cmd=cmd, background=bg):
                    p = run(cmd, background=bg)
                    self.assertEqual(p.returncode, 2, cmd)
                    self.assertIn("detaches", p.stderr)

    def test_allowed(self):
        for cmd in self.ALLOWED:
            with self.subTest(cmd=cmd):
                p = run(cmd)
                self.assertEqual(p.returncode, 0, p.stderr)


class EdgeCase(unittest.TestCase):
    def test_other_tools_pass(self):
        self.assertEqual(run("python3 server.py &", tool="Read").returncode, 0)

    def test_bad_input_fails_open(self):
        p = subprocess.run([sys.executable, str(TARGET)], input="not json", capture_output=True,
                           text=True, timeout=10)
        self.assertEqual(p.returncode, 0)

    def test_unparseable_commands_fall_back_to_a_plain_scan(self):
        # shlex cannot parse these; a lone `&` still refuses, anything else passes.
        self.assertEqual(run("echo 'unterminated &").returncode, 2)
        self.assertEqual(run("echo $'it\\'s fine' && make").returncode, 0)


if __name__ == "__main__":
    unittest.main()

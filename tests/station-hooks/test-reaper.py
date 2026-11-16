#!/usr/bin/env python3
"""Tests for the reaper.py SessionStart hook and its --report mode.
Target: the repo's hooks/reaper.py by default; HOOK_UNDER_TEST points the run at a station
copy such as ~/.claude/hooks/reaper.py.
Run: python3 tests/station-hooks/test-reaper.py   (or via unittest discover)

Contract: from a `ps` listing, report the user's heavy interpreter or agent processes that
are orphaned, or that have run under a session for over an hour; never a session itself,
another user's process, a light daemon, or an ignored one. Other events print nothing;
--report prints the same findings as plain text. Home paths and long tokens are masked.
It only reports. Fails open.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or Path(__file__).resolve().parents[2] / "hooks" / "reaper.py")
UID = os.getuid()
HOME = str(Path.home())
# Stand-in secrets in the detector's all-x placeholder form, written into LISTING below.
SECRETS = ("tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "pw_xxxxxxxx", "url_xxxxxxxx",
           "bearer_xxxxxxxxxxxxxxxx")

# pid ppid uid etime time rss command
LISTING = f"""\
    1     0     0 04-00:00:00   10:00.00   9000 /sbin/launchd
 9665     1 {UID} 01-16:17:46 1724:00.00 2150816 /opt/homebrew/bin/Python -I -
 2627     1 {UID} 03-22:38:43   9:48.91 135472 {HOME}/.bun/bin/bun {HOME}/.claude/plugins/x/worker-service.cjs --daemon
  700     1 {UID}    02:00:00   90:00.00  50000 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal
 5662     1 {UID} 01-04:17:53  300:00.00 255000 /Users/x/.local/bin/2.1.310
 7000  5662 {UID}    03:00:00    0:01.00   4000 /bin/zsh -c node build.js
 7001  7000 {UID}    03:00:00  120:00.00  80000 node {HOME}/proj/build.js --token tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
 7002  5662 {UID}    00:20:00   15:00.00  80000 python3 short-but-busy.py
 8000     1   502    05:00:00  290:00.00  80000 python3 someone-elses.py
 8100     1 {UID}    05:00:00  250:00.00  80000 python3 {HOME}/srv/ignored-daemon.py
 8200     1 {UID}    00:30:00    0:10.00 3000000 python3 big-but-idle.py --password pw_xxxxxxxx https://user:url_xxxxxxxx@example.com/x -H Authorization: Bearer bearer_xxxxxxxxxxxxxxxx
"""


def run(event: str, state: Path, listing: str = LISTING) -> subprocess.CompletedProcess:
    ps = state / "ps.txt"
    ps.write_text(listing)
    payload = {"hook_event_name": event, "session_id": "t", "source": "startup"}
    env = {**os.environ, "REAPER_PS_FILE": str(ps), "REAPER_STATE_DIR": str(state)}
    return subprocess.run([sys.executable, str(TARGET)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=10)


class ReaperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        (self.state / "reaper-ignore").write_text("# daemons I run on purpose\nignored-daemon.py\n")

    def tearDown(self):
        self.tmp.cleanup()

    def reported(self, proc: subprocess.CompletedProcess) -> str:
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"] if proc.stdout else ""

    def test_session_start_reports_the_right_set(self):
        text = self.reported(run("SessionStart", self.state))
        self.assertIn("pid 9665 (orphaned", text)        # the Nov 14 leftover
        self.assertIn("pid 7001 (long-running", text)    # a session's three-hour job
        self.assertIn("pid 8200 (orphaned", text)        # 3 GB resident with no owner
        for quiet in ("2627", "pid 700 ", "5662", "7002", "8000", "8100"):
            self.assertNotIn(f"pid {quiet.strip()} (", text, quiet)

    def test_text_masks_home_and_tokens(self):
        text = self.reported(run("SessionStart", self.state))
        self.assertNotIn(HOME, text)
        for secret in SECRETS:
            self.assertNotIn(secret, text)
        self.assertIn("[masked]", text)
        self.assertIn("untrusted data", text)
        self.assertIn("Do not stop any of them without the user's yes", text)

    def test_prompts_are_ignored(self):
        self.assertEqual(run("UserPromptSubmit", self.state).stdout, "")

    def test_report_mode_prints_plain_text(self):
        ps = self.state / "ps.txt"
        ps.write_text(LISTING)
        env = {**os.environ, "REAPER_PS_FILE": str(ps), "REAPER_STATE_DIR": str(self.state)}
        p = subprocess.run([sys.executable, str(TARGET), "--report"], env=env, capture_output=True,
                           text=True, timeout=10)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(p.stdout.startswith("reaper: 3 heavy process(es)"), p.stdout)
        self.assertIn("pid 9665", p.stdout)
        ps.write_text("    1     0     0 04-00:00:00 10:00.00 9000 /sbin/launchd\n")
        p = subprocess.run([sys.executable, str(TARGET), "--report"], env=env, capture_output=True,
                           text=True, timeout=10)
        self.assertEqual(p.stdout.strip(), "reaper: clean")

    def test_clean_machine_is_silent(self):
        p = run("SessionStart", self.state, "    1     0     0 04-00:00:00 10:00.00 9000 /sbin/launchd\n")
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_other_events_and_bad_input_fail_open(self):
        self.assertEqual(run("PreToolUse", self.state).stdout, "")
        p = subprocess.run([sys.executable, str(TARGET)], input="not json", capture_output=True,
                           text=True, timeout=10)
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()

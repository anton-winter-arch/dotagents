#!/usr/bin/env python3
"""Tests for the memory_pressure_gate.py hook.
Target: the repo's hooks/memory_pressure_gate.py by default; HOOK_UNDER_TEST points
the run at a station copy such as ~/.claude/hooks/memory_pressure_gate.py.
Run: python3 tests/station-hooks/test-memory-pressure-gate.py   (or via unittest discover)

Contract under test: a normal reading is silent; a UserPromptSubmit warn is
emitted once per episode and then stays silent while the same reason holds,
re-emits when the reason changes, and never suppresses critical; the
PreToolUse ask on a load-adding tool is unaffected by the warn record.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(os.environ.get("HOOK_UNDER_TEST")
            or Path(__file__).resolve().parents[2] / "hooks" / "memory_pressure_gate.py")


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="memgate-test-"))
        self.warn_file = self.tmp / "warned"
        self.ack_file = self.tmp / "ack"

    def tearDown(self):
        for p in self.tmp.iterdir():
            p.unlink()
        self.tmp.rmdir()

    def run_hook(self, event, level, free, swap=0, tool="", swap_ask=100000):
        env = {**os.environ,
               "MEMGATE_PRESSURE_LEVEL": str(level), "MEMGATE_FREE_PCT": str(free),
               "MEMGATE_SWAP_MB": str(swap), "MEMGATE_SWAP_ASK_MB": str(swap_ask),
               "MEMGATE_WARN_FILE": str(self.warn_file), "MEMGATE_ACK_FILE": str(self.ack_file)}
        env.pop("AGENTS_APP_SEAT", None)
        env.pop("BRAIN_SEAT", None)
        payload = {"hook_event_name": event}
        if tool:
            payload["tool_name"] = tool
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=20)
        return proc.returncode, proc.stdout, proc.stderr

    def test_normal_reading_is_silent(self):
        code, out, err = self.run_hook("UserPromptSubmit", level=1, free=60)
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertFalse(self.warn_file.exists())

    def test_prompt_warn_emits_once_per_episode(self):
        code, out, _ = self.run_hook("UserPromptSubmit", level=2, free=30)
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", out)
        self.assertIn("level 2 (warn)", out)
        self.assertTrue(self.warn_file.exists())
        code, out, err = self.run_hook("UserPromptSubmit", level=2, free=30)
        self.assertEqual((code, out, err), (0, "", ""))

    def test_prompt_warn_re_emits_when_the_reason_changes(self):
        self.run_hook("UserPromptSubmit", level=2, free=30)
        code, out, _ = self.run_hook("UserPromptSubmit", level=1, free=60, swap=200, swap_ask=100)
        self.assertEqual(code, 0)
        self.assertIn("swap in use 200 MB (warn)", out)

    def test_prompt_warn_stays_silent_however_long_the_episode_lasts(self):
        self.run_hook("UserPromptSubmit", level=2, free=30)
        old = 10 ** 9
        os.utime(self.warn_file, (old, old))
        code, out, err = self.run_hook("UserPromptSubmit", level=2, free=30)
        self.assertEqual((code, out, err), (0, "", ""))

    def test_a_normal_reading_clears_the_record_so_the_next_episode_warns(self):
        self.run_hook("UserPromptSubmit", level=2, free=30)
        self.assertTrue(self.warn_file.exists())
        # a reading just over the line flaps; it does not end the episode
        code, out, err = self.run_hook("UserPromptSubmit", level=1, free=38)
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertTrue(self.warn_file.exists())
        code, out, err = self.run_hook("UserPromptSubmit", level=1, free=60)
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertFalse(self.warn_file.exists())
        code, out, _ = self.run_hook("UserPromptSubmit", level=2, free=30)
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", out)

    def test_critical_is_never_suppressed_by_the_warn_record(self):
        self.run_hook("UserPromptSubmit", level=2, free=30)
        code, out, err = self.run_hook("UserPromptSubmit", level=4, free=5)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("critical", err)

    def test_pretooluse_ask_is_unaffected_by_the_warn_record(self):
        self.run_hook("UserPromptSubmit", level=2, free=30)
        for _ in range(2):
            code, out, _ = self.run_hook("PreToolUse", level=2, free=30, tool="Bash")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_sessionstart_warn_is_not_recorded_as_a_prompt_warning(self):
        code, out, _ = self.run_hook("SessionStart", level=2, free=30)
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", out)
        self.assertFalse(self.warn_file.exists())


if __name__ == "__main__":
    unittest.main()

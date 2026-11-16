#!/usr/bin/env python3
"""Lifecycle tests for run_evals.py: a fake skill-creator harness under a temp
HOME hangs and starts a grandchild, both tokened. The run must stop at its
--timeout cap or on SIGTERM, leave no tokened process behind, and delete its
sandbox. No real agent CLI runs.

    python3 -m unittest discover skills/ai-slop-magic-eraser/tests
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SCRIPT = SKILL / "scripts" / "run_evals.py"
HARNESS = ".claude/plugins/marketplaces/claude-plugins-official/plugins/skill-creator/skills/skill-creator"

FAKE_RUN_EVAL = r'''
import os, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", os.environ["FAKE_TOKEN"]])
time.sleep(120)
'''


def tokened(token: str) -> list[int]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    return [int(line.split()[0]) for line in out.splitlines() if token in line]


class RunEvalsLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="run-evals-test-")
        root = Path(self.tmp.name)
        scripts = root / "home" / HARNESS / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "run_eval.py").write_text(FAKE_RUN_EVAL)
        self.sandboxes = root / "tmp"
        self.sandboxes.mkdir()
        self.token = f"run-evals-test-{uuid.uuid4().hex}"
        self.env = dict(os.environ, HOME=str(root / "home"), TMPDIR=str(self.sandboxes),
                        FAKE_TOKEN=self.token)

    def tearDown(self):
        for pid in tokened(self.token):   # only this test's own tokened processes
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self.tmp.cleanup()

    def wait_for_grandchild(self, proc: subprocess.Popen) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not tokened(self.token):
            self.assertIsNone(proc.poll(), "run_evals exited before the fake harness started")
            time.sleep(0.1)
        self.assertTrue(tokened(self.token), "the fake harness never started its grandchild")

    def assert_clean(self) -> None:
        time.sleep(0.5)
        self.assertEqual(tokened(self.token), [], "a tokened process outlived run_evals")
        self.assertEqual(list(self.sandboxes.iterdir()), [], "the sandbox was not deleted")

    def test_a_hung_harness_stops_at_the_cap(self):
        started = time.monotonic()
        r = subprocess.run([sys.executable, str(SCRIPT), "--timeout", "2"], env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("passed the 2 s limit", r.stderr)
        self.assertLess(time.monotonic() - started, 30)
        self.assert_clean()

    def test_sigterm_stops_the_harness_group_and_deletes_the_sandbox(self):
        p = subprocess.Popen([sys.executable, str(SCRIPT), "--timeout", "60"], env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait_for_grandchild(p)
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=30)
        self.assertNotEqual(p.returncode, 0)
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()

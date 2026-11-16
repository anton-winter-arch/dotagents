#!/usr/bin/env python3
"""Tests for procguard.py - stdlib only, and every test runs real processes.

    python3 -m unittest discover -s skills/skill-authoring/tests

Each test tags the processes it starts with a fresh random token in their argv,
asserts on the processes carrying that token, and kills only those in tearDown.
The cases replay each way an owner can go away: a timeout, a child that ignores
SIGTERM, a grandchild left behind, the parent SIGKILLed, SIGTERMed or hung up,
and the shell around the command-line form killed.
"""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "procguard.py"
sys.path.insert(0, str(SCRIPTS))

import procguard  # noqa: E402

PY = sys.executable
SLEEPER = "import time; time.sleep(300)"
SPAWNER = ("import subprocess, sys, time\n"
           "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)', sys.argv[1]])\n"
           "time.sleep(300)")
STUBBORN = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)"
LEAVER = ("import subprocess, sys\n"
          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)', sys.argv[1]])")


def tagged(token: str) -> list:
    out = subprocess.run(["ps", "-A", "-o", "pid=,stat=,command="], capture_output=True, text=True,
                         timeout=10).stdout
    pids = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and token in parts[2] and not parts[1].startswith("Z"):
            pids.append(int(parts[0]))
    return pids


def wait_for(cond, limit: float = 10.0) -> bool:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


class Base(unittest.TestCase):
    def setUp(self):
        self.token = f"procguard-test-{uuid.uuid4().hex}"

    def tearDown(self):
        procguard.stop_all(grace=0.5)
        for pid in tagged(self.token):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def assert_gone(self, limit: float = 10.0):
        self.assertTrue(wait_for(lambda: not tagged(self.token), limit),
                        f"left running: {tagged(self.token)}")


class RunTests(Base):
    def test_output_and_status(self):
        p = procguard.run([PY, "-c", "print(42)"], timeout=10, capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, "42\n"))

    def test_input_reaches_child(self):
        p = procguard.run([PY, "-c", "import sys; print(sys.stdin.read().upper())"], timeout=10,
                          input="abc", capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "ABC")

    def test_timeout_is_required(self):
        with self.assertRaises(TypeError):
            procguard.run([PY, "-c", "pass"])  # type: ignore[call-arg]
        for bad in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                procguard.run([PY, "-c", "pass"], timeout=bad)

    def test_child_status_124_is_not_a_timeout(self):
        p = procguard.run([PY, "-c", "raise SystemExit(124)"], timeout=10)
        self.assertEqual(p.returncode, 124)

    def test_timeout_stops_the_whole_tree(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            procguard.run([PY, "-c", SPAWNER, self.token], timeout=1, grace=0.5)
        self.assert_gone(5)

    def test_sweep_does_not_depend_on_path(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            procguard.run([PY, "-c", SPAWNER, self.token], timeout=1, grace=0.5,
                          env={"PATH": "/nonexistent"})
        self.assert_gone(5)

    def test_child_ignoring_sigterm_is_killed(self):
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            procguard.run([PY, "-c", STUBBORN, self.token], timeout=1, grace=0.5)
        self.assertLess(time.monotonic() - start, 8)
        self.assert_gone(5)

    def test_grandchild_left_behind_is_swept(self):
        p = procguard.run([PY, "-c", LEAVER, self.token], timeout=30, grace=0.5)
        self.assertEqual(p.returncode, 0)
        self.assert_gone(5)

    def test_stop_all_unblocks_threads(self):
        results = []

        def worker():
            try:
                results.append(procguard.run([PY, "-c", SLEEPER, self.token], timeout=300, grace=0.5))
            except BaseException as e:  # noqa: BLE001 - any outcome counts as unblocked
                results.append(e)
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        self.assertTrue(wait_for(lambda: len(tagged(self.token)) >= 3))
        procguard.stop_all(grace=0.5)
        for t in threads:
            t.join(10)
            self.assertFalse(t.is_alive())
        self.assertEqual(len(results), 3)
        self.assert_gone(5)


class CloseTests(Base):
    def test_a_closing_stop_refuses_new_children(self):
        # In a child interpreter: closing is one-way for the process that does it.
        body = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "import procguard\n"
                "procguard.stop_all(close=True)\n"
                "try:\n"
                "    procguard.run([sys.executable, '-c', 'pass'], timeout=10)\n"
                "except RuntimeError:\n"
                "    print('refused')\n")
        p = subprocess.run([PY, "-c", body], capture_output=True, text=True, timeout=60)
        self.assertEqual(p.stdout.strip(), "refused", p.stderr)

    def test_a_signal_during_a_spawn_does_not_hang(self):
        # A signal handler runs stop_all() on the thread that may already hold the
        # lock inside popen(); the lock must let that same thread back in.
        body = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "import procguard\n"
                "with procguard._lock:\n"
                "    procguard.stop_all(close=True)\n"
                "print('returned')\n")
        p = subprocess.run([PY, "-c", body], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.stdout.strip(), "returned", p.stderr)

    def test_stopping_a_finished_group_signals_nothing(self):
        p = subprocess.Popen([PY, "-c", "pass"], start_new_session=True)
        p.wait(10)
        procguard.stop(p.pid, grace=0.5, leader_alive=False)   # must return at once, no error


class ParentDeathTests(Base):
    """A parent process that runs a spawner under procguard, then is stopped."""

    def start_parent(self, handlers: bool, capture: bool = False) -> subprocess.Popen:
        body = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r})\n"
                "import procguard\n"
                + ("procguard.install_signal_handlers()\n" if handlers else "")
                + f"procguard.run([sys.executable, '-c', {SPAWNER!r}, {self.token!r}], timeout=300, grace=0.5"
                + (", capture_output=True, text=True" if capture else "") + ")\n")
        self.tmp = tempfile.TemporaryDirectory()
        script = Path(self.tmp.name) / "parent.py"
        script.write_text(body)
        parent = subprocess.Popen([PY, str(script)], stdin=subprocess.DEVNULL)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        self.assertTrue(wait_for(lambda: len(tagged(self.token)) >= 2), "spawner never started")
        return parent

    def test_parent_sigkill(self):
        parent = self.start_parent(handlers=False)
        parent.kill()
        parent.wait(5)
        self.assert_gone(8)

    def test_parent_sigkill_while_capturing_output(self):
        # The watchdog's stderr is then a pipe whose reader is dead; its stop
        # notice must not cut the sweep short.
        parent = self.start_parent(handlers=False, capture=True)
        parent.kill()
        parent.wait(5)
        self.assert_gone(8)

    def test_parent_sigterm(self):
        parent = self.start_parent(handlers=True)
        parent.send_signal(signal.SIGTERM)
        parent.wait(10)
        self.assert_gone(8)

    def test_parent_sighup(self):
        parent = self.start_parent(handlers=True)
        parent.send_signal(signal.SIGHUP)
        parent.wait(10)
        self.assert_gone(8)


class CommandLineTests(Base):
    def test_time_limit_exit_status(self):
        p = subprocess.run([PY, str(SCRIPT), "--timeout", "1", "--grace", "0.5", "--",
                            PY, "-c", SPAWNER, self.token], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, procguard.EXIT_TIMEOUT)
        self.assertIn("time limit", p.stderr)
        self.assert_gone(5)

    def test_child_status_passes_through(self):
        p = subprocess.run([PY, str(SCRIPT), "--timeout", "10", "--", PY, "-c", "raise SystemExit(3)"],
                           timeout=30)
        self.assertEqual(p.returncode, 3)

    def test_killed_shell_stops_the_group(self):
        # `; true` keeps the shell alive as the watchdog's parent instead of exec'ing it.
        cmd = f"{PY} {SCRIPT} --timeout 300 --grace 0.5 -- {PY} -c \"{SPAWNER}\" {self.token}; true"
        shell = subprocess.Popen(["/bin/sh", "-c", cmd], stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: shell.poll() is None and shell.kill())
        self.assertTrue(wait_for(lambda: len(tagged(self.token)) >= 2), "spawner never started")
        shell.kill()
        shell.wait(5)
        self.assert_gone(8)

    def test_detached_outlives_its_caller_until_the_time_limit(self):
        cmd = f"{PY} {SCRIPT} --detached --timeout 2 --grace 0.5 -- {PY} -c \"{SPAWNER}\" {self.token}; true"
        shell = subprocess.Popen(["/bin/sh", "-c", cmd], stdin=subprocess.DEVNULL)
        self.addCleanup(lambda: shell.poll() is None and shell.kill())
        self.assertTrue(wait_for(lambda: len(tagged(self.token)) >= 2), "spawner never started")
        shell.kill()
        shell.wait(5)
        time.sleep(0.6)
        self.assertGreaterEqual(len(tagged(self.token)), 2, "a detached job must survive its caller")
        self.assert_gone(8)

    def test_requires_a_command_and_a_positive_timeout(self):
        for argv in (["--timeout", "5"], ["--timeout", "0", "--", "true"], ["--", "true"],
                     ["--timeout", "nan", "--", "true"], ["--timeout", "inf", "--", "true"],
                     ["--timeout", "5", "--det", "--", "true"],              # no abbreviations
                     ["--timeout", "5", "--timeout", "99999", "--", "true"],  # no repeats
                     ["--timeout", "5", "--grace", "61", "--", "true"]):
            p = subprocess.run([PY, str(SCRIPT), *argv], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 2, argv)


if __name__ == "__main__":
    unittest.main()

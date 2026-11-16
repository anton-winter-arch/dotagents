#!/usr/bin/env python3
"""Tests for check_spawns.py - stdlib only.

    python3 -m unittest discover -s skills/skill-authoring/tests

The rules are tested on small sources through scan_python and scan_shell, and the
CLI on a temp tree, so the suite never depends on the live repo's spawn sites.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "check_spawns.py"
sys.path.insert(0, str(SCRIPTS))

import check_spawns as cs  # noqa: E402

PROD = Path("skills/x/scripts/tool.py")
TEST = Path("skills/x/tests/test_tool.py")


def rules(src: str, path: Path = PROD) -> list[str]:
    return [rule for _, rule, _ in cs.scan_python(path, textwrap.dedent(src))]


class PythonRules(unittest.TestCase):
    def test_short_call_with_timeout_passes(self):
        self.assertEqual(rules("import subprocess\nsubprocess.run(['git', 'status'], timeout=30)\n"),
                         ["ok:short"])

    def test_missing_timeout_is_a_finding(self):
        self.assertEqual(rules("import subprocess\nsubprocess.run(['git', 'status'])\n"), ["no-timeout"])

    def test_agent_cli_needs_procguard_even_with_a_timeout(self):
        self.assertEqual(rules("import subprocess\nsubprocess.run(['claude', '-p', 'x'], timeout=60)\n"),
                         ["agent-cli"])
        self.assertEqual(rules("import subprocess\nsubprocess.run([cli_path('codex'), 'exec'], timeout=60)\n"),
                         ["agent-cli"])

    def test_raw_popen_and_os_spawns_are_findings(self):
        self.assertEqual(rules("import subprocess\nsubprocess.Popen(['sleep', '9'])\n"), ["raw-popen"])
        self.assertEqual(rules("import os\nos.system('sleep 9')\n"), ["os-spawn"])

    def test_procguard_calls_pass(self):
        self.assertEqual(rules("import procguard\nprocguard.run(['claude', '-p'], timeout=60)\n"),
                         ["ok:procguard"])

    def test_async_spawn_passes_only_through_wrap_with_a_new_session(self):
        good = "asyncio.create_subprocess_exec(*procguard.wrap(cmd, 60), start_new_session=True)\n"
        bad = "asyncio.create_subprocess_exec(*cmd)\n"
        self.assertEqual(sorted(rules(good)), ["ok:procguard", "ok:procguard"])   # the wrap and the spawn
        self.assertEqual(rules(bad), ["async-raw"])

    def test_exempt_marker_on_the_line_or_in_the_comment_block_above(self):
        same = "subprocess.Popen(argv)  # procguard: exempt - owned helper\n"
        block = ("# procguard: exempt - the registered daemon,\n"
                 "# stopped by its own down command\n"
                 "subprocess.Popen(argv)\n")
        gap = ("# procguard: exempt - not adjacent\n"
               "x = 1\n"
               "subprocess.Popen(argv)\n")
        self.assertEqual(rules(same), ["ok:exempt"])
        self.assertEqual(rules(block), ["ok:exempt"])
        self.assertEqual(rules(gap), ["raw-popen"])

    def test_test_files_may_popen_and_skip_timeouts(self):
        src = "subprocess.Popen(argv)\nsubprocess.run(argv)\nsubprocess.run(['claude', '-p'], timeout=5)\n"
        self.assertEqual(rules(src, TEST), ["ok:guard-internal", "ok:test-no-timeout", "ok:short"])

    def test_syntax_error_yields_nothing(self):
        self.assertEqual(rules("def broken(:\n"), [])


class ShellRules(unittest.TestCase):
    def scan(self, src: str) -> list[str]:
        return [rule for _, rule, _ in cs.scan_shell(Path("run.sh"), textwrap.dedent(src))]

    def test_agent_cli_without_procguard_is_a_finding(self):
        self.assertEqual(self.scan("claude -p 'hi'\n"), ["shell-agent"])
        self.assertEqual(self.scan('python3 "$repo/procguard.py" --timeout 300 -- claude -p hi\n'),
                         ["ok:procguard"])

    def test_backgrounding_is_a_finding(self):
        self.assertEqual(self.scan("server &\n"), ["shell-bg"])
        self.assertEqual(self.scan("nohup ./run.sh\n"), ["shell-bg"])
        self.assertEqual(self.scan("make && make test\ncmd > log 2>&1\n"), [])

    def test_comments_and_exemptions(self):
        self.assertEqual(self.scan("# claude -p in a comment &\n"), [])
        self.assertEqual(self.scan("# procguard: exempt - fixture server\nserver &\n"), ["ok:exempt"])


class CommandLine(unittest.TestCase):
    def test_paths_mode_skips_fixtures_and_exits_on_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=30)
            (root / "tool.py").write_text("import subprocess\nsubprocess.run(['git', 'log'])\n")
            fixture = root / "tests" / "fixture-repo"
            fixture.mkdir(parents=True)
            (fixture / "dev.sh").write_text("serve &\n")
            p = subprocess.run([sys.executable, str(SCRIPT), str(root)], cwd=root, capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn("tool.py:2\tno-timeout", p.stdout)
            self.assertNotIn("dev.sh", p.stdout)
            inv = subprocess.run([sys.executable, str(SCRIPT), "--inventory", str(root)], cwd=root,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(inv.returncode, 0)
            self.assertIn("no-timeout", inv.stdout)


if __name__ == "__main__":
    unittest.main()

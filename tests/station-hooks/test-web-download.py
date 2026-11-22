#!/usr/bin/env python3
"""Tests for web_download.py, the batch downloader the main session runs.
Target: the repo's hooks/web_download.py by default; HOOK_UNDER_TEST points the run at a
station copy such as ~/.claude/hooks/web_download.py.
Run: python3 tests/station-hooks/test-web-download.py   (or via unittest discover)

Contract: one request per item, spaced per host; a 403 stops every later item for that
host without sending it, for the session; a 429 or 503 does the same until its
Retry-After time, else for one hour; a robots-disallowed path is never requested; a redirect to
another site is not followed; files land only under a temp root; every item has a log
line; the batch is scanned once, by the scan skill's script, and never by a second
scanner. Every request goes to a server this test starts on loopback; the downloader runs
from a copy beside a stand-in scan skill.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = Path(os.environ.get("HOOK_UNDER_TEST") or REPO / "hooks" / "web_download.py")

ROBOTS = "User-agent: *\nDisallow: /private/\n\nUser-agent: ClaudeBot\nDisallow: /no-claude/\n"


class Handler(http.server.BaseHTTPRequestHandler):
    seen: list = []
    robots_status = 200

    def log_message(self, *args):
        pass

    def do_GET(self):
        Handler.seen.append((time.time(), self.path, self.headers.get("User-Agent", "")))
        if self.path == "/robots.txt":
            if Handler.robots_status != 200:
                return self.reply(Handler.robots_status, b"")
            return self.reply(200, ROBOTS.encode())
        if self.path.startswith("/refuse/"):
            return self.reply(403, b"no")
        if self.path.startswith("/down/"):
            return self.reply(503, b"maintenance")
        if self.path.startswith("/slow/"):
            return self.reply(429, b"slow down", {"Retry-After": "120"})
        if self.path == "/away":
            self.send_response(302)
            self.send_header("Location", "http://localhost:%d/ok/moved" % self.server.server_port)
            self.end_headers()
            return None
        if self.path == "/missing":
            return self.reply(404, b"")
        if self.path == "/garbage":
            self.wfile.write(b"THIS IS NOT HTTP\r\n\r\n")
            return None
        return self.reply(200, ("body of " + self.path).encode())

    def reply(self, code, body, headers=None):
        self.send_response(code)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """A plain TCP server: http.server.HTTPServer looks up its own host name at bind time,
    and that lookup can take half a minute on a machine with no reverse DNS."""
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self):
        super().server_bind()
        self.server_port = self.server_address[1]


class WebDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.seen = []
        Handler.robots_status = 200
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.scan_args = Path(self.tmp.name) / "scan-args.txt"
        self.out = os.path.join(self.tmp.name, "batch")
        self.env = dict(os.environ, TMPDIR=self.tmp.name, WEB_GUARD_DELAY="0", WEB_GUARD_CAP="20",
                        CLAUDE_CODE_SESSION_ID="dl-1", PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""))
        self.env.pop("WEB_DOWNLOAD_CONTACT", None)
        # The downloader looks for the scan skill beside its own folder first, so a copy of
        # it under the temp folder finds the stand-in below and never the real scanner.
        station = Path(self.tmp.name) / "station"
        (station / "hooks").mkdir(parents=True)
        for name in (TARGET.name, "_web_guard.py"):
            (station / "hooks" / name).write_bytes(TARGET.with_name(name).read_bytes())
        self.target = station / "hooks" / TARGET.name
        self.fake_scan = station / "skills" / "scan" / "scripts" / "scan.py"
        self.fake_scan.parent.mkdir(parents=True)
        self.scanner(0)
        # A local-security on PATH that records any call: the downloader must not use it.
        self.other_scanner = Path(self.tmp.name) / "local-security-args.txt"
        fake = self.bin / "local-security"
        fake.write_text("#!/bin/sh\nprintf '%%s\\n' \"$@\" >> \"%s\"\nexit 0\n" % self.other_scanner)
        fake.chmod(0o755)

    def scanner(self, code: int, warnings=()) -> None:
        report = json.dumps({"clamav": {"warnings": list(warnings)}})
        self.fake_scan.write_text("import sys\nopen(%r, 'a').write('\\n'.join(sys.argv[1:]) + '\\n')\n"
                                  "print(%r)\nsys.exit(%d)\n" % (str(self.scan_args), report, code))

    def test_a_clean_scan_on_old_signatures_says_so(self):
        self.scanner(0, ["signature update failed: no route", "signatures are 3.0 days old"])
        code, out, _ = self.run_tool([self.base + "/ok/w"], CLAUDE_CODE_SESSION_ID="dl-6")
        self.assertEqual(code, 0)
        self.assertIn("scan: clean (scan skill; warning: signature update failed: no route; signatures are 3.0 days old)", out)

    def run_tool(self, items, *args, **env):
        manifest = Path(self.tmp.name) / "manifest.jsonl"
        manifest.write_text("# a comment line\n" + "\n".join(
            json.dumps(i if isinstance(i, dict) else {"url": i}) for i in items) + "\n")
        p = subprocess.run([sys.executable, str(self.target), str(manifest), "--out", self.out, *args],
                           text=True, capture_output=True, env=dict(self.env, **env))
        return p.returncode, p.stdout, p.stderr

    def paths(self):
        return [p for _, p, _ in Handler.seen]

    def log(self):
        with open(os.path.join(self.out, "download-log.jsonl"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh]

    def test_a_clean_batch(self):
        code, out, err = self.run_tool([{"url": self.base + "/ok/a.txt", "why": "test"},
                                        {"url": self.base + "/ok/b.txt", "name": "../../named b.txt"},
                                        self.base + "/ok/a.txt"])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.paths(), ["/robots.txt", "/ok/a.txt", "/ok/b.txt", "/ok/a.txt"])
        self.assertEqual(sorted(os.listdir(self.out)), ["_.._named_b.txt", "a-2.txt", "a.txt", "download-log.jsonl"])
        self.assertEqual(Path(self.out, "a.txt").read_text(), "body of /ok/a.txt")
        rows = self.log()
        self.assertEqual([r["verdict"] for r in rows], ["fetched"] * 3)
        self.assertEqual(len(rows[0]["sha256"]), 64)
        self.assertEqual((rows[0]["why"], rows[0]["status"], rows[0]["bytes"]), ("test", 200, 17))
        self.assertIn("3 fetched, 0 skipped", out)
        self.assertIn("scan: clean (scan skill)", out)
        self.assertEqual(self.scan_args.read_text().split("\n")[:2], [self.out, "--json"], "one scan, of the folder")
        self.assertFalse(self.other_scanner.exists(), "local-security is not the download gate")
        self.assertTrue(all(ua.startswith("web-download/") for _, _, ua in Handler.seen))

    def test_a_403_on_the_first_of_nine_stops_the_other_eight(self):
        items = [self.base + "/refuse/1"] + [self.base + "/ok/%d" % n for n in range(8)]
        code, out, _ = self.run_tool(items)
        self.assertEqual(code, 3)
        self.assertEqual(self.paths(), ["/robots.txt", "/refuse/1"])
        self.assertIn("refused: 127.0.0.1, blocked for the session (HTTP 403)", out)
        self.assertEqual(len([r for r in self.log() if r["verdict"].startswith("skipped")]), 8)
        self.assertFalse(self.scan_args.exists(), "nothing fetched, nothing scanned")
        # The refusal outlives the run: a second run in the same session sends nothing.
        Handler.seen = []
        code, out, _ = self.run_tool([self.base + "/ok/later"])
        self.assertEqual((code, self.paths()), (3, []))
        # Another session starts clean.
        code, _, _ = self.run_tool([self.base + "/ok/later"], CLAUDE_CODE_SESSION_ID="dl-2")
        self.assertEqual((code, self.paths()), (0, ["/robots.txt", "/ok/later"]))

    def lift_blocks(self, sid: str, by: float) -> None:
        """Move the session's block lift times `by` seconds earlier, as if that time passed."""
        path = Path(self.tmp.name, "web-guard-%d" % os.getuid(), sid, "state.json")
        state = json.loads(path.read_text())
        for entry in state["hosts"].values():
            entry["until"] = entry.get("until", 0) - by if entry.get("until") else 0
        path.write_text(json.dumps(state))

    def test_a_503_skips_the_run_and_lifts_after_one_hour(self):
        items = [self.base + "/down/1"] + [self.base + "/ok/%d" % n for n in range(3)]
        code, out, _ = self.run_tool(items, CLAUDE_CODE_SESSION_ID="dl-7")
        self.assertEqual((code, self.paths()), (3, ["/robots.txt", "/down/1"]))
        self.assertRegex(out, r"refused: 127\.0\.0\.1, blocked until [0-9:]+ \(1 hour after HTTP 503\)")
        self.assertIn("(1 hour after HTTP 503)", self.log()[0]["verdict"])
        Handler.seen = []
        self.lift_blocks("dl-7", 3599)
        code, _, _ = self.run_tool([self.base + "/ok/a"], CLAUDE_CODE_SESSION_ID="dl-7")
        self.assertEqual((code, self.paths()), (3, []), "still blocked a second before the hour")
        self.lift_blocks("dl-7", 1)
        code, _, _ = self.run_tool([self.base + "/ok/a"], CLAUDE_CODE_SESSION_ID="dl-7")
        self.assertEqual((code, self.paths()), (0, ["/robots.txt", "/ok/a"]))

    def test_a_429_with_retry_after_lifts_after_that_time(self):
        code, out, _ = self.run_tool([self.base + "/slow/1", self.base + "/ok/1"], CLAUDE_CODE_SESSION_ID="dl-8")
        self.assertEqual((code, self.paths()), (3, ["/robots.txt", "/slow/1"]))
        self.assertRegex(out, r"blocked until [0-9:]+ \(Retry-After on HTTP 429\)")
        Handler.seen = []
        self.lift_blocks("dl-8", 119)
        self.run_tool([self.base + "/ok/1"], CLAUDE_CODE_SESSION_ID="dl-8")
        self.assertEqual(self.paths(), [])
        self.lift_blocks("dl-8", 1)
        code, _, _ = self.run_tool([self.base + "/ok/1"], CLAUDE_CODE_SESSION_ID="dl-8")
        self.assertEqual((code, self.paths()), (0, ["/robots.txt", "/ok/1"]))

    def test_robots_rules_are_read_first_and_obeyed(self):
        code, out, _ = self.run_tool([self.base + "/private/x", self.base + "/no-claude/y", self.base + "/ok/z"])
        self.assertEqual(code, 3)
        self.assertEqual(self.paths(), ["/robots.txt", "/ok/z"])
        self.assertEqual(out.count("robots.txt disallows this path"), 2)

    def test_a_refused_robots_request_blocks_the_host(self):
        Handler.robots_status = 403
        code, out, _ = self.run_tool([self.base + "/ok/1", self.base + "/ok/2"])
        self.assertEqual((code, self.paths()), (3, ["/robots.txt"]))
        Handler.robots_status = 404
        Handler.seen = []
        code, _, _ = self.run_tool([self.base + "/ok/1"], CLAUDE_CODE_SESSION_ID="dl-3")
        self.assertEqual((code, self.paths()), (0, ["/robots.txt", "/ok/1"]), "no robots file means no rules")

    def test_requests_to_one_host_are_spaced(self):
        code, _, _ = self.run_tool([self.base + "/ok/%d" % n for n in range(3)], WEB_GUARD_DELAY="0.3")
        self.assertEqual(code, 0)
        times = [t for t, _, _ in Handler.seen]
        self.assertTrue(all(b - a >= 0.25 for a, b in zip(times, times[1:])), times)

    def test_what_is_never_requested(self):
        code, out, _ = self.run_tool(["https://www.example.gov/a.pdf", "http://example.org/a.pdf",
                                      "ftp://example.org/a", self.base + "/away", self.base + "/missing"])
        self.assertEqual(code, 3)
        self.assertEqual(self.paths(), ["/robots.txt", "/away", "/missing"])
        self.assertIn("needs the user's yes", out)
        self.assertIn("not https", out)
        self.assertIn("redirects to another site (localhost)", out)
        self.assertIn("failed: HTTP 404", out)
        self.assertEqual(os.listdir(self.out), ["download-log.jsonl"])

    def test_the_batch_folder_must_be_under_a_temp_root(self):
        target = REPO / "tests" / "never-created"
        manifest = Path(self.tmp.name) / "m.jsonl"
        manifest.write_text(json.dumps({"url": self.base + "/ok/1"}) + "\n")
        p = subprocess.run([sys.executable, str(self.target), str(manifest), "--out", str(target)],
                           text=True, capture_output=True, env=self.env)
        self.assertEqual(p.returncode, 2)
        self.assertFalse(target.exists())
        self.assertEqual(self.paths(), [])

    def test_a_scan_finding_and_a_size_limit(self):
        self.scanner(1)
        code, out, _ = self.run_tool([self.base + "/ok/1"])
        self.assertEqual(code, 1)
        self.assertIn("scan: not clean", out)
        self.assertIn("do not open", out)
        self.scanner(4)
        code, out, _ = self.run_tool([self.base + "/ok/1"])
        self.assertEqual(code, 3)
        self.assertIn("scan: not scanned (the scan skill could not finish (exit 4)", out)
        self.assertFalse(self.other_scanner.exists(), "no second scanner is started")
        self.scanner(0)
        code, out, _ = self.run_tool([self.base + "/ok/big"], "--max-mb", "0", CLAUDE_CODE_SESSION_ID="dl-4")
        self.assertIn("larger than the size limit", out)
        self.assertNotIn("big", os.listdir(self.out))

    def test_a_broken_response_does_not_cost_the_batch_its_scan(self):
        os.makedirs(self.out)
        other = Path(self.out, "someone-elses.part")
        other.write_text("another run's file in progress")
        code, out, err = self.run_tool([self.base + "/garbage",
                                        {"url": self.base + "/ok/x", "name": "download-log.jsonl"},
                                        {"url": self.base + "/ok/y", "name": "notes.part"}])
        self.assertEqual(code, 3, out + err)
        self.assertRegex(out, r"/garbage - failed: \w+")
        self.assertIn("scan: clean", out)
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["download-log.jsonl", "file-download-log.jsonl", "notes.part_", "someone-elses.part"])
        self.assertEqual(Path(self.out, "notes.part_").read_text(), "body of /ok/y")
        self.assertEqual([r["verdict"].split(":")[0] for r in self.log()], ["failed", "fetched", "fetched"])

    def test_bad_manifests_and_no_user_agent_or_proxy_option(self):
        for text in ("", "not json\n", json.dumps({"name": "x"}) + "\n", json.dumps(["u"]) + "\n"):
            manifest = Path(self.tmp.name) / "bad.jsonl"
            manifest.write_text(text)
            p = subprocess.run([sys.executable, str(TARGET), str(manifest)], text=True, capture_output=True, env=self.env)
            self.assertEqual(p.returncode, 2, text)
        for flag in ("--user-agent", "--proxy", "--header"):
            code, _, err = self.run_tool([self.base + "/ok/1"], flag, "x")
            self.assertEqual(code, 2, flag)
        self.assertEqual(self.paths(), [])

    def test_a_run_outside_a_session_leaves_no_state(self):
        env = dict(self.env)
        env.pop("CLAUDE_CODE_SESSION_ID")
        manifest = Path(self.tmp.name) / "m.jsonl"
        manifest.write_text(json.dumps({"url": self.base + "/ok/1"}) + "\n")
        p = subprocess.run([sys.executable, str(TARGET), str(manifest), "--out", self.out, "--no-scan"],
                           text=True, capture_output=True, env=env)
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertIn("scan: not scanned (--no-scan)", p.stdout)
        root = Path(self.tmp.name) / ("web-guard-%d" % os.getuid())
        self.assertEqual([d.name for d in root.iterdir()] if root.exists() else [], [])


if __name__ == "__main__":
    unittest.main()

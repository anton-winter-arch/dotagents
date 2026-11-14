#!/usr/bin/env python3
"""Download a batch of files politely, then scan the batch once. Run by the main session.

    python3 web_download.py MANIFEST [--out DIR] [--allow-host HOST] [--max-mb N] [--no-scan]

MANIFEST has one JSON object per line: {"url": "...", "name": "file name", "why": "..."}.
`name` and `why` are optional; `why` is copied to the log. A subagent that needs files
writes the manifest and returns its path; the main session reviews it and runs this once.

What one run does, in order, for each item:

  1. Refuses anything but https (http only for loopback), a government or military host
     that is not named with --allow-host, and a host that refused a request earlier in
     this session.
  2. Reads the host's robots.txt once and skips a path it disallows for this tool, for
     Anthropic's agents or for `*`.
  3. Waits for the host's next slot (see `_web_guard.py`: a delay between requests and a
     cap per host), then sends one request with one fixed, honest User-Agent. There is no
     option to change the User-Agent or to name a proxy.
  4. On a 401, 403, 429 or 503 records the host as blocked for the session and skips its
     remaining items without sending them. A redirect to another site is not followed.
  5. Writes the file into the batch folder, which must be under a temp root, and appends
     one line to `download-log.jsonl` there: time, address, final host, status, bytes,
     SHA-256, file type and verdict.

Then the batch folder is scanned once, with `local-security scan path` where that command
is installed and accepts the folder, else with the scan skill's script. Nothing downloaded
is executed. The summary is counts plus every refusal, skip and failed scan.

Exit 0: every item fetched and the scan clean. 1: the scan was not clean. 2: bad
arguments. 3: something was skipped, refused or not scanned.
Stdlib only, Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

USER_AGENT = "web-download/1.0 (agent batch downloader; honors robots.txt; one request at a time)"
ROBOT_NAMES = ("web-download", "Claude-User", "ClaudeBot", "anthropic-ai")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
IP_LITERAL = re.compile(r"^([0-9.]+|[0-9a-f:]*:[0-9a-f:.]*)$")
LOG_NAME = "download-log.jsonl"
ITEM_SECONDS = 600       # one item may take this long, however slowly the bytes arrive
CHUNK = 1 << 16
# What a request can raise besides an HTTP status: http.client's own errors (a bad status
# line, a truncated body) pass through urllib unwrapped.
NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError)
SCAN_SKILL = ("skills/scan/scripts/scan.py",)


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OtherSite(Exception):
    def __init__(self, host: str) -> None:
        super().__init__(host)
        self.host = host


def site(host: str) -> str:
    """The last two labels of a host name, a rough stand-in for 'the same site'. An address
    literal or a single-label name is its own site, whole."""
    if IP_LITERAL.match(host) or "." not in host:
        return host
    return ".".join(host.split(".")[-2:])


class SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only within the same site, and never down from https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        old_host, new_host = (old.hostname or "").lower(), (new.hostname or "").lower()
        same_scheme = new.scheme == "https" or (new.scheme == "http" and old.scheme == "http")
        if not same_scheme or site(old_host) != site(new_host):
            raise OtherSite(new_host or newurl[:60])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def user_agent() -> str:
    """The fixed User-Agent, plus a contact a site may ask for, taken from the environment."""
    contact = re.sub(r"[^A-Za-z0-9@._:/+ -]", "", os.environ.get("WEB_DOWNLOAD_CONTACT", ""))[:100]
    return USER_AGENT[:-1] + "; " + contact + ")" if contact else USER_AGENT


def safe_name(item: dict, index: int, folder: str) -> str:
    raw = str(item.get("name") or os.path.basename(urlsplit(item["url"]).path) or "")
    name = SAFE_NAME.sub("_", raw).lstrip(".")[:120] or "download-%d" % index
    if name == LOG_NAME:
        name = "file-" + name                     # never the run's own log
    if name.endswith(".part"):
        name += "_"                               # never a name this run uses for a partial file
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(folder, name)):
        name, n = "%s-%d%s" % (stem, n, ext), n + 1
    return name


def file_type(path: str) -> str:
    program = shutil.which("file")
    if not program:
        return ""
    try:
        out = subprocess.run([program, "-b", "--mime-type", path], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()[:80]


class Run:
    def __init__(self, guard, sid: str, out: str, allow: set, max_bytes: int) -> None:
        self.guard, self.sid, self.out, self.allow, self.max_bytes = guard, sid, out, allow, max_bytes
        self.opener = urllib.request.build_opener(SameSiteRedirects)
        self.robots: dict = {}
        self.fetched: list[str] = []
        self.skipped: list[tuple[str, str]] = []
        self.refused: dict = {}

    def log(self, **record) -> None:
        record["time"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with open(os.path.join(self.out, LOG_NAME), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def slot(self, host: str) -> str:
        """Book and wait for the host's next slot. Returns '' or the reason not to send."""
        with self.guard.locked(self.sid) as state:
            verdict, value = self.guard.reserve(state, host)
        if verdict == "blocked":
            self.refused.setdefault(host, int(value))
            return "the host refused a request earlier in this session (HTTP %d)" % value
        if verdict == "cap":
            return "the per-host limit of %d requests is reached" % value
        if value > 0:
            time.sleep(value)
        return ""

    def refuse(self, host: str, code: int) -> None:
        with self.guard.locked(self.sid) as state:
            self.guard.refuse(state, host, code)
        self.refused[host] = code

    def open(self, url: str):
        return self.opener.open(urllib.request.Request(url, headers={"User-Agent": user_agent()}), timeout=60)

    def robots_for(self, scheme: str, host: str, netloc: str):
        """The host's parsed robots rules, None when everything is allowed, or a reason string."""
        if host in self.robots:
            return self.robots[host]
        reason = self.slot(host)
        rules = None
        if reason:
            rules = reason
        else:
            try:
                with self.open("%s://%s/robots.txt" % (scheme, netloc)) as resp:
                    text = resp.read(500_000).decode("utf-8", "replace")
                rules = urllib.robotparser.RobotFileParser()
                rules.parse(text.splitlines())
            except urllib.error.HTTPError as exc:
                if exc.code in self.guard.REFUSAL_CODES:
                    self.refuse(host, exc.code)
                    rules = "the host refused the robots.txt request (HTTP %d)" % exc.code
                elif exc.code >= 500:
                    rules = "robots.txt could not be read (HTTP %d)" % exc.code
            except OtherSite:
                rules = None
            except NETWORK_ERRORS:
                rules = "robots.txt could not be read"
        self.robots[host] = rules
        return rules

    def item(self, index: int, item: dict) -> None:
        url = str(item.get("url") or "")
        parts = urlsplit(url)
        host = self.guard.host_of(url)
        skip = ""
        if not host:
            skip = "not an http or https address"
        elif parts.scheme != "https" and not self.guard.is_local(host):
            skip = "not https"
        elif self.guard.is_strict(host) and host not in self.allow:
            skip = "a government or military host: needs the user's yes, then --allow-host %s" % host
        elif host in self.refused:
            skip = "the host refused a request earlier in this run (HTTP %d)" % self.refused[host]
        if not skip:
            rules = self.robots_for(parts.scheme, host, parts.netloc)
            if isinstance(rules, str):
                skip = rules
            elif rules is not None and not all(rules.can_fetch(name, url) for name in ROBOT_NAMES):
                skip = "robots.txt disallows this path"
        if not skip:
            skip = self.slot(host)
        if skip:
            self.skipped.append((url, skip))
            self.log(url=url, final_host=host, status=0, bytes=0, verdict="skipped: " + skip, why=item.get("why", ""))
            return
        self.fetch(index, item, url, host)

    def fetch(self, index: int, item: dict, url: str, host: str) -> None:
        name = safe_name(item, index, self.out)
        part = os.path.join(self.out, name + ".part")
        try:
            self.receive(item, url, host, name, part)
        finally:                                  # only this item's own partial file, whatever went wrong
            if os.path.exists(part):
                os.remove(part)

    def receive(self, item: dict, url: str, host: str, name: str, part: str) -> None:
        digest, size, status, final, verdict = hashlib.sha256(), 0, 0, host, ""
        deadline = time.time() + ITEM_SECONDS
        try:
            with self.open(url) as resp, open(part, "wb") as fh:
                status = resp.status
                final = (urlsplit(resp.geturl()).hostname or host).lower()
                while True:
                    chunk = resp.read1(CHUNK)     # one receive at a time, so the deadline below is checked often
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        verdict = "skipped: larger than the size limit"
                        break
                    if time.time() > deadline:
                        verdict = "skipped: took longer than the time limit"
                        break
                    digest.update(chunk)
                    fh.write(chunk)
        except urllib.error.HTTPError as exc:
            status = exc.code
            if exc.code in self.guard.REFUSAL_CODES:
                self.refuse(host, exc.code)
                verdict = "refused: HTTP %d" % exc.code
            else:
                verdict = "failed: HTTP %d" % exc.code
        except OtherSite as exc:
            verdict = "skipped: redirects to another site (%s); name that address in the manifest if it is the source" % exc.host
        except NETWORK_ERRORS as exc:
            verdict = "failed: %s" % type(exc).__name__
        if verdict:
            self.skipped.append((url, verdict))
            self.log(url=url, final_host=final, status=status, bytes=0, verdict=verdict, why=item.get("why", ""))
            return
        path = os.path.join(self.out, name)
        os.replace(part, path)
        os.chmod(path, 0o600)
        self.fetched.append(path)
        self.log(url=url, final_host=final, status=status, bytes=size, sha256=digest.hexdigest(),
                 type=file_type(path), file=name, verdict="fetched", why=item.get("why", ""))


def scan(folder: str) -> tuple[str, str]:
    """Scan the batch folder once. Returns (verdict, scanner): 'clean', 'not clean' or 'not scanned'."""
    program = shutil.which("local-security")
    if program:
        try:
            code = subprocess.run([program, "scan", "path", folder], capture_output=True, timeout=900).returncode
        except (OSError, subprocess.SubprocessError):
            code = 4
        if code in (0, 1):
            return ("clean" if code == 0 else "not clean"), "local-security"
        # Only exit 2 (not configured, or the folder is outside its roots) falls back. A
        # timeout behind another scan (5) or a tool failure (4) does not: the fallback would
        # start a second scanner beside the one already running.
        if code != 2:
            reason = "waited too long behind another scan" if code == 5 else "the scanner failed (exit %d)" % code
            return "not scanned", "local-security: %s; run `local-security scan path` on the folder later" % reason
    here = Path(__file__).resolve().parent
    for root in (here.parent, Path.home() / ".agents", Path.home() / ".claude"):
        script = root / SCAN_SKILL[0]
        if script.is_file():
            try:
                code = subprocess.run([sys.executable, str(script), folder, "--json"],
                                      capture_output=True, timeout=900).returncode
            except (OSError, subprocess.SubprocessError):
                return "not scanned", "scan skill failed to run"
            if code == 0:
                return "clean", "scan skill"
            if code in (1, 3):
                return "not clean", "scan skill"
            return "not scanned", "scan skill is incomplete (exit %d); run it by hand" % code
    return "not scanned", "no scanner found"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download a manifest of files politely, then scan the batch.")
    ap.add_argument("manifest")
    ap.add_argument("--out", help="batch folder, under a temp root; default: beside the manifest")
    ap.add_argument("--allow-host", action="append", default=[],
                    help="a government or military host the user approved for this run")
    ap.add_argument("--max-mb", type=int, default=200)
    ap.add_argument("--no-scan", action="store_true")
    args = ap.parse_args(argv)

    guard = sibling("_web_guard")
    try:
        with open(args.manifest, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        items = [json.loads(ln) for ln in lines]
    except (OSError, ValueError) as exc:
        print("web_download: cannot read the manifest: %s" % type(exc).__name__, file=sys.stderr)
        return 2
    if not items or not all(isinstance(i, dict) and isinstance(i.get("url"), str) for i in items):
        print("web_download: each manifest line is a JSON object with a url", file=sys.stderr)
        return 2
    out = os.path.abspath(args.out or os.path.join(os.path.dirname(os.path.abspath(args.manifest)),
                                                   "downloads-" + time.strftime("%Y%m%d-%H%M%S")))
    if not guard.under_temp(os.path.dirname(out)):
        print("web_download: the batch folder must be under a temp root, not %s" % out, file=sys.stderr)
        return 2
    os.makedirs(out, mode=0o700, exist_ok=True)

    sid = guard.session_id()
    own_state = not sid
    if own_state:
        sid = "run-%d" % os.getpid()
    run = Run(guard, sid, out, {h.lower() for h in args.allow_host}, args.max_mb * 1_000_000)
    for index, item in enumerate(items, start=1):
        try:
            run.item(index, item)
        except Exception as exc:                  # one bad item never costs the batch its scan
            run.skipped.append((str(item.get("url")), "failed: %s" % type(exc).__name__))
    try:
        with guard.locked(sid) as state:
            guard.note_download_dir(state, out)
        if own_state:
            shutil.rmtree(guard.state_dir(sid), ignore_errors=True)
    except (OSError, ValueError):
        pass

    verdict, scanner = ("not scanned", "nothing fetched") if not run.fetched else \
        (("not scanned", "--no-scan") if args.no_scan else scan(out))
    print("web_download: %d fetched, %d skipped, %d host(s) refused" % (len(run.fetched), len(run.skipped), len(run.refused)))
    for host, code in sorted(run.refused.items()):
        print("  refused: %s (HTTP %d); its remaining items were not requested" % (host, code))
    for url, why in run.skipped:
        print("  skipped: %s - %s" % (url, why))
    print("scan: %s (%s)" % (verdict, scanner))
    if verdict == "not clean":
        print("  do not open the files in this folder; tell the user")
    print("folder: %s" % out)
    print("log: %s" % os.path.join(out, "download-log.jsonl"))
    if verdict == "not clean":
        return 1
    if run.skipped or run.refused or (run.fetched and verdict != "clean"):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

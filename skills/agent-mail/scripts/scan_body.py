#!/usr/bin/env python3
"""scan_body.py - refuse a message whose subject or body holds sensitive information.

Usage: scan_body.py --subject TEXT --body FILE

Runs the sibling `sanitize` skill's `tree` scan over the subject and body. A hit in
any class except home paths (agents point each other at code by path) is a refusal:
exit 9 with the classes and counts on stderr, never the matched value. Emails at the
reserved example domains (example.com/.net/.org, *.example, *.test, *.invalid,
*.localhost) are stripped before the scan, since they never belong to a real person,
and so are redaction markers ({redacted-email}), all-x placeholders (price_xxxxxxxx)
and fictional 555-01xx phone numbers.
When sanitize is not installed, prints a warning and exits 0: the message is sent
unscanned. When the station term list is unreadable, scans without it and says so.

AGENT_MAIL_SCANNER overrides the path to sanitize.py (tests).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_CLASSES = {"home_path"}
# The domain must END at the reserved label: a real domain that merely contains an
# example label (mail.example.com.<real-domain>) stays in the scan. A sentence-ending
# period is not a label.
RESERVED_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)*"
    r"(?:example\.(?:com|net|org)|example|test|invalid|localhost)(?![A-Za-z0-9-]|\.[A-Za-z0-9-])", re.I)
# Redaction markers and all-x placeholders are what a careful sender writes instead
# of a value: {redacted-password}, price_xxxxxxxx, sk_test_XXXXXXXXXXXX.
# Every segment is short and letters only, so a real key with an x-run tacked on
# the end (sk_live_<key>_xxxx, AKIA<key>_xxxx, sk-proj-<key>_xxxx) is still scanned.
PLACEHOLDER = re.compile(r"\{redacted[-_][A-Za-z0-9_-]+\}|\b[A-Za-z]{1,12}_(?:[A-Za-z]{1,12}_)*[xX*]{4,}\b")
# 555-0100 to 555-0199 is the range reserved for fiction ((312) 555-0123).
FICTIONAL_PHONE = re.compile(r"(?<![\d-])(?:\(?\d{3}\)?[-. ]?)?555[-. ]?01\d\d(?![\d-])")


def scanner() -> Path:
    env = os.environ.get("AGENT_MAIL_SCANNER")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "sanitize" / "scripts" / "sanitize.py"


def run(scan: Path, target: Path, station: bool):
    cmd = [sys.executable, str(scan), "tree"] + ([] if station else ["--no-station-terms"]) + [str(target)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="")
    ap.add_argument("--body", required=True)
    a = ap.parse_args()
    scan = scanner()
    if not scan.is_file():
        print("agent-mail: WARNING - sanitize is not installed, so this message was sent without a "
              "sensitive-content scan. Check it holds no credentials or personal data.", file=sys.stderr)
        return 0
    text = a.subject + "\n\n" + Path(a.body).read_text(encoding="utf-8", errors="replace")
    text = RESERVED_EMAIL.sub("reserved-example-address", text)
    text = FICTIONAL_PHONE.sub("fictional-number", PLACEHOLDER.sub("placeholder", text))
    with tempfile.TemporaryDirectory(prefix="agent-mail-scan-") as d:
        target = Path(d) / "message.md"
        target.write_text(text, encoding="utf-8")
        r = run(scan, target, station=True)
        if r.returncode == 2 and "station term list" in r.stderr:
            print("agent-mail: note - the station term list is not readable here, so the scan ran "
                  "without it.", file=sys.stderr)
            r = run(scan, target, station=False)
    if r.returncode not in (0, 1):
        print(f"agent-mail: the sensitive-content scan failed (exit {r.returncode}); not sending. "
              f"{r.stderr.strip()[:300]}", file=sys.stderr)
        return 9
    try:
        removed = json.loads(r.stdout).get("removed", {})
    except ValueError:
        print("agent-mail: the sensitive-content scan returned unreadable output; not sending.", file=sys.stderr)
        return 9
    hits = {k: v for k, v in removed.items() if k not in ALLOWED_CLASSES and v}
    if not hits:
        return 0
    found = ", ".join(f"{k} {v}" for k, v in sorted(hits.items()))
    print(f"SENSITIVE_CONTENT: the subject or body holds {found}. Agent mail never holds credentials, "
          f"personal data, client identifiers or production data. Name where the thing lives (a file "
          f"path, an env var name, a settings key) instead of the value, then send again.", file=sys.stderr)
    return 9


if __name__ == "__main__":
    sys.exit(main())

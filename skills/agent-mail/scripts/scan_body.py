#!/usr/bin/env python3
"""scan_body.py - refuse a message whose subject or body holds sensitive information.

Usage: scan_body.py --subject TEXT --body FILE

Runs the sibling `sanitize` skill's detectors (scripts/detect.py, the one rule source)
over the subject and body and reads them through its agent-mail severity table: a
secret, an email or phone outside the reserved and fictional ranges, an identifier
shape, a station term or a hidden-character attack is a refusal, exit 9 with the classes
and counts on stderr, never the matched value. Home paths and GUIDs pass, since agents
point each other at code by path. The reserved example domains, redaction markers,
all-x placeholders and fictional 555-01xx numbers are the engine's own allowances.
When sanitize is not installed, prints a warning and exits 0: the message is sent
unscanned. When the station term list is unreadable, scans without it and says so.

AGENT_MAIL_SCANNER overrides the path to sanitize.py (tests); its folder must hold detect.py.
"""

import argparse
import os
import sys
from pathlib import Path


def scanner() -> Path:
    env = os.environ.get("AGENT_MAIL_SCANNER")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "sanitize" / "scripts" / "sanitize.py"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="")
    ap.add_argument("--body", required=True)
    a = ap.parse_args()
    scan = scanner()
    if not scan.is_file() or not (scan.parent / "detect.py").is_file():
        print("agent-mail: WARNING - sanitize is not installed, so this message was sent without a "
              "sensitive-content scan. Check it holds no credentials or personal data.", file=sys.stderr)
        return 0
    try:
        sys.path.insert(0, str(scan.parent))
        import detect
    except Exception as exc:
        print(f"agent-mail: the sensitive-content scan failed to load ({type(exc).__name__}); not sending.",
              file=sys.stderr)
        return 9
    text = a.subject + "\n\n" + Path(a.body).read_text(encoding="utf-8", errors="replace")
    terms = detect.station_terms_lenient()
    if terms is None:
        print("agent-mail: note - the station term list is not readable here, so the scan ran "
              "without it.", file=sys.stderr)
    counts: dict[str, int] = {}
    for hit in detect.find(text, terms):
        if detect.severity("mail", hit) == detect.BLOCK:
            counts[hit.cls] = counts.get(hit.cls, 0) + 1
    if not counts:
        return 0
    found = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"SENSITIVE_CONTENT: the subject or body holds {found}. Agent mail never holds credentials, "
          f"personal data, client identifiers or production data. Name where the thing lives (a file "
          f"path, an env var name, a settings key) instead of the value, then send again.", file=sys.stderr)
    return 9


if __name__ == "__main__":
    sys.exit(main())

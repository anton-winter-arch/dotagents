#!/usr/bin/env python3
"""Deterministic scanner for instructions hidden in characters a reviewer cannot see.

EXECUTE this before merging any file an agent will read as instructions -
SKILL.md, agent/command definitions, rules, hooks, settings, inbox messages.

The threat is specific to agent tooling. A human reviewing a diff sees rendered
text; the model reads the codepoints. Characters that render as nothing, or that
reorder what is displayed, let an attacker put one instruction on the screen and
a different one in the model's context. The reviewer approves what they saw.

  - TAG characters (U+E0000-U+E007F) mirror ASCII inside an invisible plane.
    A full sentence of them renders as zero pixels. There is no legitimate use
    in source or prose; this is the "ASCII smuggling" prompt-injection vector.
  - BIDI overrides (U+202A-U+202E, U+2066-U+2069) reorder display without
    reordering the bytes - the Trojan Source attack (CVE-2021-42574).
  - ZERO-WIDTH characters (U+200B-U+200D, U+2060, U+FEFF, and the filler
    codepoints) hide token boundaries and split keywords past a naive grep.
  - VARIATION SELECTORS (U+FE00-U+FE0F, U+E0100-U+E01EF) carry hidden payload
    bytes too, but also appear in legitimate emoji sequences, so they WARN.

Stdlib only. Offline. No network, no subprocess.

This tool FAILS CLOSED. A file it cannot decode or that exceeds the size cap is
reported as a finding, never silently skipped - an adversary must not be able to
pad or re-encode a file past the gate.

    python3 unicode_smuggle_check.py <path>...      # exit 1 on any FAIL
    python3 unicode_smuggle_check.py --json <path>
    python3 unicode_smuggle_check.py --strict <path>   # WARN also exits 1

The codepoint table lives in the sanitize skill (skills/sanitize/scripts/detect.py),
the one rule source; this scanner reports the rows that table marks "fail" or "warn".
A missing table is a FAIL, never a clean run.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

FAIL, WARN = "FAIL", "WARN"

MAX_FILE_BYTES = 5_000_000

TEXT_SUFFIXES = {
    ".md", ".mdx", ".txt", ".json", ".yml", ".yaml", ".toml", ".sh", ".bash",
    ".zsh", ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".rb", ".ps1",
}

DETECT_DIR = Path(__file__).resolve().parents[2] / "sanitize" / "scripts"
try:
    sys.path.insert(0, str(DETECT_DIR))
    import detect  # noqa: E402
except Exception:                                   # reported per run in main()
    detect = None

SEVERITY = {"fail": FAIL, "warn": WARN}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    column: int
    severity: str
    rule: str
    codepoint: str
    message: str


def classify(cp: int) -> tuple[str, str, str] | None:
    """Return (severity, rule, why) for a dangerous codepoint, else None. Cosmetic rows
    of the shared table (exotic spaces, soft hyphens) are not this scanner's concern."""
    found = detect.codepoint_rule(chr(cp))
    if not found or found[1] not in SEVERITY:
        return None
    rule, smuggle, why = found
    return SEVERITY[smuggle], rule, why


def codepoint_name(cp: int) -> str:
    try:
        return unicodedata.name(chr(cp))
    except ValueError:
        return "unnamed"


def scan_text(text: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for col, ch in enumerate(line, start=1):
            cp = ord(ch)
            if cp < 0x80:  # fast path - plain ASCII is the overwhelming majority
                continue
            # A BOM at the very start of the file is a legitimate encoding marker.
            if cp == 0xFEFF and lineno == 1 and col == 1:
                continue
            verdict = classify(cp)
            if verdict is None:
                continue
            severity, rule, why = verdict
            findings.append(Finding(
                path=path,
                line=lineno,
                column=col,
                severity=severity,
                rule=rule,
                codepoint=f"U+{cp:04X}",
                message=f"{codepoint_name(cp)}: {why}",
            ))
    return findings


def scan_file(path: Path) -> list[Finding]:
    p = str(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [Finding(p, 0, 0, FAIL, "unreadable", "-", f"cannot read file: {exc}")]
    if len(raw) > MAX_FILE_BYTES:
        return [Finding(p, 0, 0, FAIL, "oversize", "-",
                        f"file is {len(raw)} bytes, over the {MAX_FILE_BYTES} cap - "
                        "review by hand rather than skipping")]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [Finding(p, 0, 0, FAIL, "undecodable", "-",
                        f"not valid UTF-8 ({exc.reason}) - a re-encoded file can hide "
                        "codepoints from this scan")]
    return scan_text(text, p)


def iter_targets(roots: list[str]) -> list[Path]:
    targets: list[Path] = []
    for root in roots:
        path = Path(root)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if any(part in {".git", "node_modules", "__pycache__"} for part in child.parts):
                    continue
                if child.is_file() and child.suffix.lower() in TEXT_SUFFIXES:
                    targets.append(child)
        else:
            targets.append(path)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="files or directories to scan")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--strict", action="store_true", help="exit 1 on WARN as well as FAIL")
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    if detect is None:
        findings.append(Finding(str(DETECT_DIR / "detect.py"), 0, 0, FAIL, "table-missing", "-",
                                "the shared codepoint table did not load, so nothing was checked - "
                                "a check that did not run is not a clean result"))
    else:
        for target in iter_targets(args.paths):
            findings.extend(scan_file(target))

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        for f in findings:
            location = f"{f.path}:{f.line}:{f.column}" if f.line else f.path
            print(f"{f.severity} {location} [{f.rule}] {f.codepoint} {f.message}")
        if not findings:
            print("clean - no hidden or display-reordering characters found")

    failed = any(f.severity == FAIL for f in findings)
    warned = any(f.severity == WARN for f in findings)
    return 1 if failed or (args.strict and warned) else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Deterministic pre-review sweep over a session's changed files.

EXECUTE this before spawning a reviewer at closeout. Everything it catches is a
finding the reviewer no longer has to spend a pass on.

An adversarial review is expensive and its budget should go to judgment calls -
a rule that changes behavior for every future session, a claim that contradicts
the table below it, a config row that would clobber station state. What it
actually gets spent on is proofreading: a shell block referencing a variable
nothing assigns, an ordered list numbered off by one against the headings it
mirrors, "three rules" standing above four bullets, a station path in a file
bound for publication. Those classes are decidable without a model, so they are
decided here.

Two kinds of check. The content checks are the sanitize skill's detectors
(skills/sanitize/scripts/detect.py, the one rule source) read through its review
severity table; this file holds no content pattern of its own:

  - station-path         an absolute home directory or an email address, which
                         is a personal constant in anything published
  - credential-shape     a secret shape (FAIL), or a private-key header with no
                         key material under it (WARN)
  - work-item-id, role-code, env-catalog
                         identifier shapes, surfaced as candidates (WARN) for the
                         reviewer to rule on, since whether a token names
                         something real needs context this tool does not have;
                         stand-in values (repdigits, sequences) are filtered out
  - identifier-term      a station term-list entry; FAIL in a file that travels,
                         WARN under PROJECTS/, tasks/, DRAFTS/ and __archive/
  - invisible-unicode    a character that hides or reorders text (FAIL), or a
                         variation selector (WARN)

The prose checks are this file's own:

  - undefined-shell-var  a fenced shell block references a variable no block in
                         the file assigns, so the documented command cannot run
  - ordinal-mismatch     an ordered list whose numbering is not contiguous, or
                         which disagrees with the Step/Phase headings it counts
  - count-mismatch       "N <things>:" standing above a list or table that does
                         not hold N of them
  - dead-xref            a relative markdown link pointing at a file that does
                         not exist

A content finding names the line and the class, never the matched value.

This tool never edits. It reports, and the operator rules on what it found.

It also classifies the diff, because how hard the review works is a function of
what the diff can reach. A change to a hook, a script, a subagent definition or a
permission file executes on every future session on every machine; a change to
prose is read by whoever opens it. The first deserves the full adversarial pass,
the second deserves one focused pass. The tier is printed so the choice is
visible rather than silent.

    python3 closeout_lint.py                 # the session's changed files
    python3 closeout_lint.py <path>...       # explicit files or directories
    python3 closeout_lint.py --tier          # classify only, no sweep
    python3 closeout_lint.py --json
    python3 closeout_lint.py --strict        # WARN also exits 1

A linter does not replace verification. It reads text against itself; it cannot
tell you that a sentence which parses cleanly is false. The claim-checking half
of a review stays with the reviewer.

Every check is tuned to stay silent on documentation that describes OTHER repos,
because most skill prose does. A path in a fenced block, a backticked filename
from the target project, a placeholder link like `[text](url)` - all of those are
correct writing, and a sweep that flagged them would be muted within a week.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

FAIL, WARN = "FAIL", "WARN"

TEXT_SUFFIXES = {
    ".md", ".mdx", ".txt", ".json", ".yml", ".yaml", ".toml", ".sh", ".bash",
    ".zsh", ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".rb", ".ps1",
}

SANITIZE_SCRIPTS = Path(__file__).resolve().parents[2] / "sanitize" / "scripts"
MAX_FILE_BYTES = 5_000_000


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    severity: str
    rule: str
    message: str


# --------------------------------------------------------------------------
# shared markdown parsing

FENCE = re.compile(r"^\s*(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+-]*)")
BULLET = re.compile(r"^(\s*)[-*+]\s+\S")
ORDERED = re.compile(r"^(\s*)(\d+)\.\s+\S")


def iter_fenced_blocks(lines: list[str]):
    """Yield (lang, first_line_number, block_lines) for each fenced code block."""
    i, n = 0, len(lines)
    while i < n:
        opening = FENCE.match(lines[i])
        if not opening:
            i += 1
            continue
        marker, lang = opening.group(1), opening.group(2).lower()
        start = i + 1
        j = start
        while j < n:
            closing = FENCE.match(lines[j])
            if (closing and not closing.group(2)
                    and closing.group(1)[0] == marker[0]
                    and len(closing.group(1)) >= len(marker)):
                break
            j += 1
        yield lang, start + 1, lines[start:j]
        i = j + 1


def fenced_line_numbers(lines: list[str]) -> set[int]:
    """1-based line numbers that sit inside a fenced code block."""
    inside: set[int] = set()
    for _lang, first, block in iter_fenced_blocks(lines):
        inside.update(range(first, first + len(block)))
    return inside


def block_items(lines: list[str], start: int) -> int | None:
    """Count the items of the list or table beginning at or after `start`.

    Returns None when no list or table follows. Nested items do not count -
    a claim about "four rules" is a claim about the top level.
    """
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None

    if lines[i].lstrip().startswith("|"):
        rows = 0
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            cells = lines[i].strip().strip("|")
            if not re.fullmatch(r"[\s:|-]+", cells):
                rows += 1
            i += 1
        return max(rows - 1, 0)  # the header is not an item

    opener = BULLET.match(lines[i]) or ORDERED.match(lines[i])
    if not opener or len(opener.group(1)) >= 2:
        # An indented block belongs to something else - a quoted example, a
        # nested illustration - not to the claim above it.
        return None

    items = 0
    blanks = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            blanks += 1
            if blanks > 1:
                break
            i += 1
            continue
        marker = BULLET.match(line) or ORDERED.match(line)
        if marker:
            if len(marker.group(1)) < 2:
                items += 1
            blanks = 0
            i += 1
            continue
        if line.startswith((" ", "\t")):  # continuation of the current item
            blanks = 0
            i += 1
            continue
        break
    return items


# --------------------------------------------------------------------------
# check 1 - undefined shell variables

SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console", "shell-session"}

VAR_REF = re.compile(r"(?<!\\)\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")
FOR_VAR = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
READ_VAR = re.compile(r"\bread\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)")
# awk, jq and perl carry their own $-syntax that shells never expand
FOREIGN_SYNTAX = re.compile(r"\b(awk|jq|perl)\b")

AMBIENT_VARS = frozenset("""
HOME PWD OLDPWD USER LOGNAME PATH SHELL TERM LANG LC_ALL TMPDIR TMP EDITOR
VISUAL HOSTNAME UID EUID GROUPS RANDOM SECONDS LINENO REPLY OSTYPE MACHTYPE
BASH BASH_SOURCE BASH_VERSION FUNCNAME PIPESTATUS PS1 PS2 IFS SHLVL PAGER
XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME COLUMNS LINES DISPLAY
""".split())


def check_shell_vars(lines: list[str], path: str) -> list[Finding]:
    findings: list[Finding] = []
    defined: set[str] = set()
    for lang, first, block in iter_fenced_blocks(lines):
        if lang not in SHELL_LANGS:
            continue
        for offset, line in enumerate(block):
            code = line.split("#", 1)[0]
            defined.update(ASSIGN.findall(code))
            defined.update(FOR_VAR.findall(code))
            defined.update(READ_VAR.findall(code))
            if FOREIGN_SYNTAX.search(code):
                continue
            for name in VAR_REF.findall(code):
                if name in defined or name in AMBIENT_VARS or name.startswith("CLAUDE"):
                    continue
                findings.append(Finding(
                    path, first + offset, FAIL, "undefined-shell-var",
                    f"${name} is referenced but nothing in this file assigns it - "
                    "the documented command runs against an empty value",
                ))
                defined.add(name)  # report each name once per file
    return findings


# --------------------------------------------------------------------------
# content checks - the sanitize skill's detectors at the review severity

RULES = {
    "home_path": ("station-path", "an absolute home directory - a personal constant that does not "
                                  "survive publication or another machine; use $HOME or a neutral placeholder"),
    "email": ("station-path", "an email address is a personal constant"),
    "secret": ("credential-shape", "a credential shape - treat it as issued until proven otherwise, and "
                                   "rotate it if it ever reached a remote"),
    "key_header": ("credential-shape", "a private-key header with no key material under it - benign in a "
                                       "fixture or a rule table, a leak anywhere else"),
    "work_item": ("work-item-id", "a live tracker item's shape with digits that are not an obvious "
                                  "stand-in - confirm it names nothing real, or use a repdigit, a "
                                  "sequential run or an NNNNnn placeholder"),
    "role_code": ("role-code", "reads as a person's initials with a role code"),
    "catalog": ("env-catalog", "reads as an environment-prefixed catalog name"),
    "term": ("identifier-term", "a station term-list entry - a private project, client or person "
                                "identifier unless it is an ordinary word here"),
}


class Engine:
    """The sanitize detectors, loaded once. `error` is set when the engine is missing, and
    a missing engine is reported as a FAIL: a check that did not run is not a clean result."""

    def __init__(self, root: Path):
        self.error = ""
        self.detect = None
        self.terms: set[str] = set()
        self.terms_skipped = False
        try:
            sys.path.insert(0, str(SANITIZE_SCRIPTS))
            import detect
        except Exception as exc:                          # missing or broken engine
            self.error = f"{type(exc).__name__}"
            return
        self.detect = detect
        listed = detect.station_terms_lenient()
        self.terms_skipped = listed is None
        self.terms = set(listed or ()) | detect.project_aliases(root)

    def check(self, text: str, path: str) -> list[Finding]:
        if self.detect is None:
            return []
        findings: list[Finding] = []
        for hit in self.detect.find(text, self.terms):
            level = self.detect.severity("review", hit, path)
            if level is None:
                continue
            severity = FAIL if level == self.detect.BLOCK else WARN
            line = self.detect.line_of(text, hit.start)
            if hit.cls == "invisible":
                ch = text[hit.start]
                why = self.detect.codepoint_rule(ch)[2]
                findings.append(Finding(path, line, severity, "invisible-unicode",
                                        f"U+{ord(ch):04X} [{hit.rule}] {why}"))
                continue
            rule, message = RULES.get(hit.cls, (hit.cls, "flagged by the sanitize detectors"))
            findings.append(Finding(path, line, severity, rule, message))
        return findings


# --------------------------------------------------------------------------
# check 5 - ordered lists that disagree with themselves or with their headings

STEP_HEADING = re.compile(r"^#{1,6}\s+(?:Step|Phase)\s+(\d+)\b", re.IGNORECASE)


def collect_ordered_lists(lines: list[str]) -> list[tuple[int, list[int]]]:
    """Return (first_line_number, numbers) for each top-level ordered list."""
    fenced = fenced_line_numbers(lines)
    lists: list[tuple[int, list[int]]] = []
    current: list[int] = []
    start = 0
    blanks = 0
    for lineno, line in enumerate(lines, start=1):
        if lineno in fenced:
            continue
        marker = ORDERED.match(line)
        if marker and len(marker.group(1)) < 2:
            if not current:
                start = lineno
            current.append(int(marker.group(2)))
            blanks = 0
            continue
        if not line.strip():
            blanks += 1
            if blanks > 1 and current:
                lists.append((start, current))
                current = []
            continue
        if current and not (line.startswith((" ", "\t")) or BULLET.match(line)):
            lists.append((start, current))
            current = []
        blanks = 0
    if current:
        lists.append((start, current))
    return [item for item in lists if len(item[1]) > 1]


def check_ordinals(lines: list[str], path: str) -> list[Finding]:
    findings: list[Finding] = []
    headings = [int(m.group(1)) for m in (STEP_HEADING.match(ln) for ln in lines) if m]
    for start, numbers in collect_ordered_lists(lines):
        if len(set(numbers)) == 1:
            continue  # lazy numbering (every item "1.") is idiomatic markdown
        ascending = list(range(numbers[0], numbers[0] + len(numbers)))
        descending = list(range(numbers[0], numbers[0] - len(numbers), -1))
        if numbers not in (ascending, descending):
            findings.append(Finding(
                path, start, FAIL, "ordinal-mismatch",
                f"ordered list is numbered {numbers} - not a contiguous run from "
                f"{numbers[0]}",
            ))
            continue
        if len(headings) > 1 and len(numbers) == len(headings) and numbers != headings:
            findings.append(Finding(
                path, start, FAIL, "ordinal-mismatch",
                f"ordered list numbers {numbers} but the Step/Phase headings it "
                f"mirrors are {headings}",
            ))
    return findings


# --------------------------------------------------------------------------
# check 6 - "N things:" standing above a list that does not hold N of them

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

COUNTABLE = frozenset("""
rules items steps outcomes shapes checks conditions reasons things options
phases gates findings columns rows cases ways kinds parts sections points
questions criteria classes tiers commands flags fields keys entries bullets
examples bodies skills agents tools modes states levels layers sources targets
defects traps guards hooks scripts tests suites stations harnesses decisions
proposals slices places copies branches
""".split())

# The noun alternation lives inside the pattern so the lazy adjective run
# backtracks until it reaches a countable word: "six skill bodies" is a claim
# about bodies, not about skill.
COUNT_CLAIM = re.compile(
    r"\b(" + "|".join(NUMBER_WORDS) + r"|\d{1,2})\s+(?:[a-z][a-z-]*\s+){0,2}?"
    r"(" + "|".join(sorted(COUNTABLE, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def check_counts(lines: list[str], path: str) -> list[Finding]:
    fenced = fenced_line_numbers(lines)
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        if lineno in fenced or not line.rstrip().endswith(":"):
            continue
        claims = [
            (NUMBER_WORDS.get(num.lower(), None) if not num.isdigit() else int(num), noun)
            for num, noun in COUNT_CLAIM.findall(line)
            if noun.lower() in COUNTABLE
        ]
        claims = [(n, noun) for n, noun in claims if n is not None]
        if not claims:
            continue
        actual = block_items(lines, lineno)  # lineno is 1-based, so this is the next line
        if actual is None or actual == 0:
            continue
        if any(n == actual for n, _ in claims):
            continue
        claimed, noun = claims[-1]
        findings.append(Finding(
            path, lineno, FAIL, "count-mismatch",
            f"claims {claimed} {noun} but {actual} follow",
        ))
    return findings


# --------------------------------------------------------------------------
# check 7 - relative links pointing at nothing

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "#", "//")

# Only navigational links are checked - a target carrying a path separator. A
# bare word or filename inside parentheses is nearly always documenting link
# syntax itself, [text](url), and resolving it would flag correct prose.
def check_xrefs(lines: list[str], path: str, source: Path, root: Path) -> list[Finding]:
    fenced = fenced_line_numbers(lines)
    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        if lineno in fenced:
            continue
        for target in MD_LINK.findall(line):
            if target.startswith(EXTERNAL) or target.startswith(("~", "$", "<")):
                continue
            bare = target.split("#", 1)[0]
            if not bare or "/" not in bare or "*" in bare:
                continue
            candidate = Path(bare)
            if candidate.is_absolute():
                continue  # an absolute path is the station-path check's business
            if (source.parent / candidate).exists() or (root / candidate).exists():
                continue
            findings.append(Finding(
                path, lineno, FAIL, "dead-xref",
                f"link target '{target}' does not exist",
            ))
    return findings


# --------------------------------------------------------------------------
# tiering - what the diff can reach decides how hard the review works

EXECUTABLE_SUFFIXES = frozenset({
    ".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl",
    ".ps1", ".bat", ".cmd", ".toml",
})
# a subagent definition, a slash command and a hook are all instructions some
# harness executes; a permission or trust file decides what it may execute
EXECUTABLE_DIRS = frozenset({
    "hooks", "agents", "commands", ".github", ".claude", ".cursor", ".codex",
    ".copilot", ".gemini",
})


# A shell block inside a SKILL.md is copied and run verbatim by every session that
# follows the skill, so the path suffix says "prose" while the content is a command.
# Tagged fences only - an untagged block is as often output as input.
SHELL_FENCE_RE = re.compile(r"^\s*```+\s*(bash|sh|zsh|shell|console)\s*$",
                            re.IGNORECASE)


def has_command_block(path: Path) -> bool:
    """True if a prose file carries a runnable shell block."""
    try:
        with path.open(encoding="utf-8") as handle:
            return any(SHELL_FENCE_RE.match(line) for line in handle)
    except (OSError, UnicodeDecodeError):
        return False


def tier_of(paths: list[Path], root: Path) -> tuple[str, list[str], list[str]]:
    """Return ("A"|"B", the paths that decided A, prose paths holding commands)."""
    deciders: list[str] = []
    command_files: list[str] = []
    for path in paths:
        try:
            rel = path.resolve().relative_to(root.resolve())
        except ValueError:
            rel = path
        name = rel.name.lower()
        if (rel.suffix.lower() in EXECUTABLE_SUFFIXES
                or any(part in EXECUTABLE_DIRS for part in rel.parts[:-1])
                or (name.startswith("settings") and name.endswith(".json"))
                or name in {".mcp.json", "cli-config.json", "permissions.json"}):
            deciders.append(str(rel))
        elif has_command_block(path):
            command_files.append(str(rel))
    return ("A" if deciders else "B"), deciders, command_files


def describe_tier(tier: str, deciders: list[str], swept: int,
                  command_files: list[str] | None = None) -> str:
    command_files = command_files or []
    # named rather than folded into the tier: escalating a docs diff to a full
    # adversarial pass over one example block is how a gate gets ignored
    extra = ""
    if command_files:
        listed = "\n".join(f"  {p}" for p in command_files)
        extra = (f"\n  command blocks in prose, {len(command_files)} file(s):\n"
                 f"{listed}\n"
                 "  add the command-execution domain for these, and only these")
    if tier == "A":
        listed = "\n".join(f"  {p}" for p in deciders)
        return (f"tier: A - executable surface, {len(deciders)} of {swept} file(s)\n"
                f"{listed}\n"
                "  full adversarial review: this reaches every future session" + extra)
    body = "prose and specs" if command_files else "prose and specs, none executable"
    return (f"tier: B - {body}, {swept} file(s)\n"
            "  one focused pass: check the cheap factual claims against reality" + extra)


# --------------------------------------------------------------------------
# driving

def repo_root(start: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(out) if out else start
    except (OSError, subprocess.CalledProcessError):
        return start


def git_changed_paths(root: Path) -> list[Path]:
    names: set[str] = set()
    for cmd in (["git", "diff", "--name-only", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            out = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                                 check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        names.update(line.strip() for line in out.splitlines() if line.strip())
    return [root / name for name in sorted(names) if (root / name).is_file()]


def expand(paths: list[str]) -> list[Path]:
    targets: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if any(part in {".git", "node_modules", "__pycache__"} for part in child.parts):
                    continue
                if child.is_file() and child.suffix.lower() in TEXT_SUFFIXES:
                    targets.append(child)
        else:
            targets.append(path)
    return targets


def scan_file(path: Path, root: Path, engine: Engine) -> list[Finding]:
    display = str(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [Finding(display, 0, WARN, "unreadable", f"skipped: {exc.strerror or type(exc).__name__}")]
    # Oversize and undecodable files fail rather than skip: a padded or re-encoded file
    # must not walk past the hidden-character check.
    if len(raw) > MAX_FILE_BYTES:
        return [Finding(display, 0, FAIL, "oversize", f"{len(raw)} bytes, over the {MAX_FILE_BYTES} "
                                                        "cap - review it by hand rather than skipping it")]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [Finding(display, 0, FAIL, "undecodable", f"not valid UTF-8 ({exc.reason}) - a re-encoded "
                                                           "file can hide codepoints from this check")]
    lines = text.splitlines()
    findings = engine.check(text, display)
    if path.suffix.lower() in {".md", ".mdx"}:
        findings += check_shell_vars(lines, display)
        findings += check_ordinals(lines, display)
        findings += check_counts(lines, display)
        findings += check_xrefs(lines, display, path, root)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*",
                        help="files or directories; default is the session's changed files")
    parser.add_argument("--tier", action="store_true",
                        help="classify the diff and stop, without sweeping")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--strict", action="store_true", help="exit 1 on WARN as well as FAIL")
    args = parser.parse_args(argv)

    root = repo_root(Path.cwd())
    changed = expand(args.paths) if args.paths else git_changed_paths(root)
    tier, deciders, command_files = tier_of(changed, root)
    targets = [p for p in changed if p.suffix.lower() in TEXT_SUFFIXES and p.is_file()]

    if args.tier:
        if args.json:
            print(json.dumps({"tier": tier, "deciders": deciders,
                              "command_files": command_files,
                              "files": len(changed)}, indent=2))
        else:
            print(describe_tier(tier, deciders, len(changed), command_files))
        return 0

    engine = Engine(root)
    findings: list[Finding] = []
    if engine.error and targets:
        findings.append(Finding(
            str(SANITIZE_SCRIPTS / "detect.py"), 0, FAIL, "engine-missing",
            f"the sanitize detectors did not load ({engine.error}), so secrets, station paths, "
            "identifiers and hidden characters were NOT checked - a step that did not run is "
            "not a clean result"))
    for target in targets:
        findings.extend(scan_file(target, root, engine))
    findings.sort(key=lambda f: (f.path, f.line))
    terms = "skipped" if engine.terms_skipped else "checked"

    if args.json:
        print(json.dumps({"tier": tier, "deciders": deciders,
                          "command_files": command_files, "terms": terms,
                          "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(describe_tier(tier, deciders, len(changed), command_files))
        if engine.terms_skipped and targets:
            print("  the station term list is not readable here, so the term check was skipped")
        print()
        for f in findings:
            location = f"{f.path}:{f.line}" if f.line else f.path
            print(f"{f.severity} {location} [{f.rule}] {f.message}")
        if not findings:
            print(f"clean - {len(targets)} file(s) swept, no mechanical findings")

    failed = any(f.severity == FAIL for f in findings)
    warned = any(f.severity == WARN for f in findings)
    return 1 if failed or (args.strict and warned) else 0


if __name__ == "__main__":
    sys.exit(main())

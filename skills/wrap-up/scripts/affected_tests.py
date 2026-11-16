#!/usr/bin/env python3
"""Run only the tests that cover what changed - never a whole-repo sweep.

    python3 affected_tests.py                 # files changed against HEAD, staged or not, plus new files
    python3 affected_tests.py --files A B     # exactly these files (a fix's own files)
    python3 affected_tests.py --list          # print the plan, run nothing
    python3 affected_tests.py --both          # also run on the newest python3, not only the 3.9 floor

Each changed file maps to the one check that covers it:

  a code file under a folder with tests/      that folder's suite (the nearest one up the tree)
  a folder whose suite is pytest (pyproject)  `uv run --offline pytest -q` there
  hooks/<name>.py or .sh                      tests/station-hooks/test-<name>.*
  hooks/manifest.json                         the hook seeder's suite
  a test file                                 that file's own suite
  a procguard.py copy identical to the        tests/test_procguard_copies.py only: its behavior
    canonical file                            is tested once, in skill-authoring
  skills/*/SKILL.md                           check_descriptions.py
  any other doc or data file                  nothing

Every changed .py or .sh file also gets the spawn lint, on those files only. Suites run one
at a time, each under a 900 s cap, on the 3.9 floor by default. Exit 1 when any check fails.

A check that passed is never rerun on the same content: each pass records a hash of what the
check reads (a suite's whole folder, or a test file plus the changed files behind it) in
~/.local/state/affected-tests/passed.json, and a later run skips that check while the hash
still matches. So a test run right after an edit is the closeout run for that code, and a fix
reruns only the suites it touched. `--force` ignores the record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CANONICAL_GUARD = Path("skills/skill-authoring/scripts/procguard.py")
FLOOR = "/usr/bin/python3"
SUITE_TIMEOUT = 900
# Station state, outside every repo: which check passed on which exact content.
STATE = Path(os.environ.get("AFFECTED_TESTS_STATE")
             or Path.home() / ".local" / "state" / "affected-tests" / "passed.json")


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         timeout=30, check=True).stdout.strip()
    return Path(out)


def changed_files(root: Path) -> list[str]:
    tracked = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "HEAD"], capture_output=True,
                             text=True, timeout=60, check=True).stdout.splitlines()
    new = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                         capture_output=True, text=True, timeout=60, check=True).stdout.splitlines()
    return sorted({p for p in tracked + new if p})


def nearest_suite(root: Path, rel: Path) -> Path | None:
    """The closest folder at or above `rel` that has a tests/ folder of its own."""
    folder = (root / rel).parent
    while folder != root and root in folder.parents:
        if folder.name == "tests":
            folder = folder.parent
            continue
        if (folder / "tests").is_dir():
            return folder
        folder = folder.parent
    return None


def plan(root: Path, files: list[str]) -> tuple[list[tuple], list[str]]:
    """(checks, files to lint). A check is (label, kind, path)."""
    checks: dict[tuple, None] = {}
    lint: list[str] = []
    canonical = (root / CANONICAL_GUARD).read_bytes() if (root / CANONICAL_GUARD).is_file() else b""
    for f in files:
        rel = Path(f)
        full = root / rel
        if not full.is_file():
            continue                                   # deleted: nothing left to test
        if rel.suffix in (".py", ".sh"):
            lint.append(f)
        if rel.name == "procguard.py" and rel != CANONICAL_GUARD and full.read_bytes() == canonical:
            checks[("procguard copies", "file", "tests/test_procguard_copies.py")] = None
            continue
        if rel.parts[0] == "hooks" and len(rel.parts) == 2:
            if rel.name == "manifest.json":
                checks[("hook seeder", "suite", "skills/agent-cc-configs-sync")] = None
                continue
            stem = rel.stem.lstrip("_").replace("_", "-")
            tests_dir = root / "tests" / "station-hooks"
            found = sorted(tests_dir.glob(f"test-{stem}.*"))
            if not found:      # a hook tested inside another hook's file
                found = [t for t in sorted(tests_dir.glob("test-*"))
                         if t.is_file() and rel.name in t.read_text(encoding="utf-8", errors="replace")]
            for test in found:
                checks[(test.name, "file", str(test.relative_to(root)))] = None
            if rel.name == "procguard.py":
                checks[("procguard copies", "file", "tests/test_procguard_copies.py")] = None
            continue
        if rel.parts[0] == "tests" and rel.name.startswith("test") and rel.suffix in (".py", ".sh"):
            checks[(rel.name, "file", f)] = None
            continue
        if rel.suffix == ".md":
            if len(rel.parts) == 3 and rel.parts[0] == "skills" and rel.name == "SKILL.md":
                checks[("skill descriptions", "file", "skills/skill-authoring/scripts/check_descriptions.py")] = None
            continue
        if rel.suffix not in (".py", ".sh", ".json", ".js", ".cjs", ".ts", ".toml", ".sql"):
            continue
        suite = nearest_suite(root, rel)
        if suite is not None:
            name = str(suite.relative_to(root))
            kind = "pytest" if (suite / "pyproject.toml").is_file() else "suite"
            checks[(name, kind, name)] = None
    unique: dict[tuple, tuple] = {}
    for label, kind, path in checks:
        unique.setdefault((kind, path), (label, kind, path))
    return list(unique.values()), lint


SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".pytest_cache", ".code-kg", "markdown-kg", "vault-kg", ".git"}


def fingerprint(root: Path, kind: str, path: str, files: list[str], py: str) -> str:
    """A hash of everything a check reads: a suite's whole folder, or a single test
    file plus the changed files that led to it. Same hash, same result."""
    h = hashlib.sha256(f"{kind}\0{path}\0{py}\0".encode())
    if kind in ("suite", "pytest"):
        members = sorted(p for p in (root / path).rglob("*")
                         if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts)
                         and p.suffix != ".db")
    else:
        members = sorted({root / path, *(root / f for f in files if (root / f).is_file())})
    for p in members:
        h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def load_passed() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_passed(passed: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(passed, indent=0, sort_keys=True))
        os.replace(tmp, STATE)
    except OSError:
        pass


def run_check(root: Path, kind: str, path: str, py: str) -> tuple[bool, str]:
    if kind == "pytest":
        if not shutil.which("uv"):
            return False, "uv is not installed"
        cmd, cwd = ["uv", "run", "--offline", "pytest", "-q", "-p", "no:cacheprovider"], root / path
    elif kind == "suite":
        cmd, cwd = [py, "-m", "unittest", "discover", "-s", "tests"], root / path
    elif path.endswith(".sh"):
        cmd, cwd = ["bash", path], root
    else:
        cmd, cwd = [py, path], root
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=SUITE_TIMEOUT,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"ran past {SUITE_TIMEOUT} s"
    tail = [ln for ln in (p.stderr + p.stdout).splitlines() if ln.strip()]
    summary = next((ln for ln in reversed(tail) if ln.startswith(("Ran ", "OK", "FAILED")) or " passed" in ln),
                   tail[-1] if tail else "")
    return p.returncode == 0, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run only the tests that cover the changed files.")
    ap.add_argument("--files", nargs="+", help="these files instead of everything changed against HEAD")
    ap.add_argument("--list", action="store_true", help="print the plan and run nothing")
    ap.add_argument("--both", action="store_true", help="run on the newest python3 as well as the 3.9 floor")
    ap.add_argument("--force", action="store_true", help="rerun checks that already passed on this content")
    a = ap.parse_args(argv)
    root = repo_root()
    files = a.files or changed_files(root)
    checks, lint = plan(root, files)
    pys = [FLOOR if Path(FLOOR).is_file() else sys.executable]
    if a.both and sys.executable not in pys:
        pys.append(sys.executable)
    print(f"{len(files)} changed file(s): {len(checks)} check(s), spawn lint on {len(lint)} file(s)")
    if a.list:
        for label, kind, path in checks:
            print(f"  {kind:<6} {path}")
        return 0
    failed = 0
    if lint:
        lint_script = root / "skills" / "skill-authoring" / "scripts" / "check_spawns.py"
        p = subprocess.run([pys[0], str(lint_script), *[str(root / f) for f in lint]], cwd=root,
                           capture_output=True, text=True, timeout=300)
        ok = p.returncode == 0
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} spawn lint: {(p.stdout + p.stderr).strip().splitlines()[-1:]}")
    passed = {} if a.force else load_passed()
    skipped = 0
    for label, kind, path in checks:
        for py in pys if kind != "pytest" else pys[:1]:
            tag = "" if kind == "pytest" else f" [{Path(py).name if py != FLOOR else '3.9'}]"
            key = f"{kind}:{path}:{py}"
            mark = fingerprint(root, kind, path, files, py)
            if passed.get(key) == mark:
                skipped += 1
                print(f"skip {path}{tag}: passed on this exact content")
                continue
            ok, summary = run_check(root, kind, path, py)
            failed += not ok
            if ok:
                passed[key] = mark
                save_passed(passed)
            print(f"{'ok  ' if ok else 'FAIL'} {path}{tag}: {summary}")
    if skipped:
        print(f"{skipped} check(s) skipped: unchanged since they last passed (--force reruns them)")
    print(f"{failed} failing" if failed else "all affected checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

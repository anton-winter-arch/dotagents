#!/usr/bin/env python3
"""Stop the closeout review from looping: a review settled once is not run again.

    python3 review_gate.py check                  # exit 0 PASS, exit 1 REVIEW plus what changed
    python3 review_gate.py close findings.json    # exit 1 while any finding is open

`close` runs once, after every finding of the one review is fixed or dismissed. It
records the staged set and the working tree (tracked and untracked files, ignored
ones excepted) in the repo's git directory. `check` compares both with that record:

  PASS     nothing changed since the close; skip the review and the fixes
  REVIEW   lists the files changed since the close, or says no review was closed

The findings file is a JSON list of {"finding", "status", "reason"}, `[]` when the
review found nothing or was skipped. A status of "fixed" or "dismissed" settles a
finding; a dismissal needs a reason.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STATE_NAME = "wrap-up-review.json"
SETTLED = {"fixed", "dismissed"}


def git(*args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=120,
                          check=True, env=env).stdout.strip()


def state_path() -> Path:
    return Path(git("rev-parse", "--absolute-git-dir")) / STATE_NAME


def tree_now() -> str:
    """Hash the whole working tree through a throwaway index; the real index is untouched."""
    index = Path(git("rev-parse", "--absolute-git-dir")) / "index"
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "index"
        if index.exists():
            # copy2 keeps the index's mtime, which git's racy-entry check depends on.
            shutil.copy2(index, scratch)
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
        git("add", "-A", env=env)
        return git("write-tree", env=env)


def open_findings(path: str) -> list[str]:
    items = json.loads(Path(path).read_text())
    problems = []
    for item in items:
        name = str(item.get("finding", "?"))
        status = item.get("status")
        if status not in SETTLED:
            problems.append(f"open: {name}")
        elif status == "dismissed" and not str(item.get("reason", "")).strip():
            problems.append(f"dismissed without a reason: {name}")
    return problems


def check() -> int:
    state = state_path()
    if not state.exists():
        print("REVIEW: no review has been closed in this repo")
        return 1
    record = json.loads(state.read_text())
    closed, now = record.get("tree", ""), tree_now()
    staged_same = record.get("index") == git("write-tree")
    if now == closed and staged_same:
        print("PASS: nothing changed since the review was closed; skip the review")
        return 0
    try:
        changed = git("diff", "--name-only", closed, now).splitlines()
    except subprocess.CalledProcessError:
        print("REVIEW: the closed review's record is gone")
        return 1
    print("REVIEW: changed since the review was closed:")
    if not staged_same:
        print("  (the staged set)")
    for name in changed:
        print(f"  {name}")
    return 1


def close(path: str) -> int:
    problems = open_findings(path)
    if problems:
        print("NOT CLOSED:")
        for line in problems:
            print(f"  {line}")
        return 1
    record = {"tree": tree_now(), "index": git("write-tree")}
    state_path().write_text(json.dumps(record) + "\n")
    print("CLOSED: the review is settled; do not run it again")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["check"] and len(argv) == 1:
        return check()
    if argv[:1] == ["close"] and len(argv) == 2:
        return close(argv[1])
    print(__doc__.strip().splitlines()[2], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

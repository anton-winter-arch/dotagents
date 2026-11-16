#!/usr/bin/env python3
"""SessionStart hook: tell the user, once a day, when an agent harness the bench uses
has a newer release.

Fires only in the repository that holds the task skill's tryout bench (the session's
CLAUDE_PROJECT_DIR must be that repository's root, found from the skill's own path, so
no path is hard-coded); in any other project it exits at once and leaves the stamp
alone. Runs only at session startup and only if it has not run yet on the current local
date: the first thing it does is compare the date in its stamp file with today and
exit silently when they match, so every later session that day costs one file read
and no network call. Otherwise it writes today's date to the stamp, then runs
the bench's `versions --quiet` (`task.py tryout versions`), which compares the installed goose, pi, dsh and
deepagents-code against their latest published releases (Homebrew, npm's `latest`
tag, PyPI; alpha and beta tracks are never followed) and prints a line only when
something is newer.

The line goes to the user as a systemMessage and to the model as additionalContext.
It never upgrades anything. A missing bench, a timeout or a network failure is
silent: the stamp is already written, so a failure does not retry until tomorrow.

Environment overrides (tests):
  HARNESS_VERSION_STAMP    stamp file (default ~/.local/state/harness-bench/version-check.stamp)
  HARNESS_BENCH_SCRIPT     the harness_bench.py to run
  HARNESS_VERSION_REPO     the repository root the hook fires in (default: five levels
                           above the script, <repo>/skills/task/tryout/scripts/)
  HARNESS_VERSION_TODAY    the date to treat as today, YYYY-MM-DD
  HARNESS_VERSION_TIMEOUT  seconds before the check and everything it started are killed (12)
"""

import datetime
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

HOME = Path.home()
STAMP = Path(os.environ.get("HARNESS_VERSION_STAMP") or HOME / ".local/state/harness-bench/version-check.stamp")
SCRIPT = Path(os.environ.get("HARNESS_BENCH_SCRIPT") or HOME / ".agents/skills/task/tryout/scripts/harness_bench.py")
def timeout_s() -> float:
    try:
        return float(os.environ.get("HARNESS_VERSION_TIMEOUT") or 12)
    except ValueError:
        return 12.0


def in_bench_repo() -> bool:
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project:
        return False
    repo = Path(os.environ.get("HARNESS_VERSION_REPO") or SCRIPT.resolve().parents[4])
    try:
        return Path(project).resolve() == repo.resolve()
    except OSError:
        return False


def main() -> int:
    if not in_bench_repo():
        return 0
    today = os.environ.get("HARNESS_VERSION_TODAY") or datetime.date.today().isoformat()
    try:
        if STAMP.read_text(encoding="utf-8").strip() == today:
            return 0
    except OSError:
        pass
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(today + "\n", encoding="utf-8")
    except OSError:
        return 0
    if not SCRIPT.is_file():
        return 0
    try:
        # Under procguard: a slow `brew info` or `--version` grandchild stops with it at the
        # timeout, and the whole group stops if the harness kills this hook first.
        out = sibling("procguard").run([sys.executable, str(SCRIPT), "versions", "--quiet"],
                                       capture_output=True, text=True, timeout=timeout_s(),
                                       grace=0.5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 0
    if not out:
        return 0
    line = "".join(ch for ch in out.splitlines()[-1] if ch.isprintable())[:400]
    print(json.dumps({"systemMessage": line, "suppressOutput": True,
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

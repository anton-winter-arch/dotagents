#!/usr/bin/env python3
"""PreToolUse hook on the shell: warn when a git commit or push targets a repo other than the session's home repo.

Several agent sessions work side by side, each in its own repo. A commit or push that
lands in another session's repo writes into work that session owns. This hook does not
block; it tells the model (additionalContext) and the user (systemMessage) that the
target is outside home, so the step is a choice rather than an accident.

The home repo is the git top level of the first of:
  1. AGENT_HOME_REPO, an explicit pin (set it in a project's .claude/settings.json "env")
  2. CLAUDE_PROJECT_DIR, the folder the session was started in, which Claude Code passes
     to every hook and which does not move when the shell changes directory
  3. the payload's cwd
The target is worked out from the command text: a leading `cd <dir>`, `git -C <dir>`
(repeatable, each relative to the last), `--git-dir=` and `--work-tree=`. A path held in
a variable or reached through `bash -c` is not seen; this is the honest-case warning,
not a sandbox. Exit 0 on every path, and silent on any internal error.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_input = _load("_input")
_shell_dirs = _load("_shell_dirs")

WATCHED = {"commit", "push"}
# A lookup gets LOOKUP_TIMEOUT s on a stalled mount; the home lookup plus MAX_LOOKUPS targets stays under the
# binding's 10 s.
LOOKUP_TIMEOUT = 2
MAX_LOOKUPS = 3


def toplevel(path: str) -> str | None:
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", path, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=LOOKUP_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def home_dir(cwd: str) -> str:
    return os.environ.get("AGENT_HOME_REPO") or os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd()


def targets(command: str, cwd: str) -> list[tuple[str, str]]:
    """(subcommand, directory) for every watched git call in the command."""
    found = []
    for words, here in _shell_dirs.walk(command, cwd):
        if Path(words[0]).name != "git":
            continue
        where, i = _shell_dirs.git_target(words, here)
        if i < len(words) and words[i] in WATCHED:
            found.append((words[i], os.path.normpath(where)))
    return found


def main() -> int:
    ev = _input.read_event()
    if ev.tool_class != "shell" or "git" not in ev.command:
        return 0
    calls = targets(ev.command, ev.cwd)
    if not calls:
        return 0
    home_root = toplevel(home_dir(ev.cwd))
    roots: dict[str, str | None] = {}
    outside = []
    unchecked = 0
    for sub, where in calls:
        if where not in roots:
            if len(roots) >= MAX_LOOKUPS:
                unchecked += 1
                continue
            roots[where] = toplevel(where)
        root = roots[where]
        if root and root != home_root and (sub, root) not in outside:
            outside.append((sub, root))
    if not outside:
        return 0

    def shown(path: str) -> str:
        # Repo paths come from the command text: printable characters only and a per-path cap, so a crafted
        # folder name cannot add lines to the model's context or crowd out the question below.
        return repr("".join(ch for ch in path if ch.isprintable())[:200])

    named = "; ".join(f"git {sub} in {shown(root)}" for sub, root in outside[:3])
    if unchecked:
        named += f" (and {unchecked} more git call(s) not checked)"
    home = shown(home_root) if home_root else "no git repo (the session's start folder is not inside one)"
    text = (f"Cross-repo git: this command runs {named}, but this session's home repo is {home}. "
            "Are you sure this session should commit or push there right now? Another session may own that "
            "repo's working tree. If this is intended, carry on; if not, stop and ask the user.")
    print(json.dumps({"systemMessage": text,
                      "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)

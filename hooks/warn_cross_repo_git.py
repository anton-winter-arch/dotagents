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
import re
import shlex
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_input", Path(__file__).with_name("_input.py"))
_input = importlib.util.module_from_spec(_spec)
sys.modules["_input"] = _input
_spec.loader.exec_module(_input)

WATCHED = {"commit", "push"}
# A lookup gets LOOKUP_TIMEOUT s on a stalled mount; the home lookup plus MAX_LOOKUPS targets stays under the
# binding's 10 s.
LOOKUP_TIMEOUT = 2
MAX_LOOKUPS = 3
SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
PREFIXES = {"sudo", "env", "command", "nohup", "time", "rtk", "proxy"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


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
    here = cwd or os.getcwd()
    found = []
    for segment in SEPARATORS.split(command or ""):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        while words and (words[0] in PREFIXES or ASSIGNMENT.match(words[0])):
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd":
            dest = words[1] if len(words) > 1 else str(Path.home())
            here = os.path.join(here, os.path.expanduser(dest))
            continue
        if Path(words[0]).name != "git":
            continue
        where, i = here, 1
        while i < len(words) and words[i].startswith("-"):
            w = words[i]
            if w == "-C" and i + 1 < len(words):
                where = os.path.join(where, os.path.expanduser(words[i + 1]))
                i += 2
                continue
            if w.startswith("--work-tree="):
                where = os.path.join(where, os.path.expanduser(w.split("=", 1)[1]))
            elif w.startswith("--git-dir="):
                where = os.path.dirname(os.path.join(where, os.path.expanduser(w.split("=", 1)[1])).rstrip("/"))
            elif w in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(words):
                if w == "--work-tree":
                    where = os.path.join(where, os.path.expanduser(words[i + 1]))
                elif w == "--git-dir":
                    where = os.path.dirname(os.path.join(where, os.path.expanduser(words[i + 1])).rstrip("/"))
                i += 2
                continue
            i += 1
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

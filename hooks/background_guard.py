#!/usr/bin/env python3
"""PreToolUse hook on the shell: background work runs under procguard, or not at all.

A local Claude Code session puts no time limit on a background command, and stopping a task
can leave the processes it started running. That is how a forgotten benchmark held a CPU
core for 40 hours. This hook enforces the house lifecycle standard
(skills/skill-authoring/references/process-lifecycle.md) for agent shell commands:

1. A `run_in_background` command must be exactly one procguard call, optionally after
   `cd <dir>` steps:
       python3 ~/.claude/hooks/procguard.py --timeout <seconds> -- <command>
   The script must be this station's procguard by content (a skill's byte-identical copy
   counts). Before `--` only `--timeout N` (1 to MAX_TIMEOUT) and `--grace N` (0 to
   MAX_GRACE) are allowed, each once; procguard itself refuses abbreviations and repeats,
   so the line read here is the line that runs. A wrapped command that is itself a
   detacher (`setsid`, `nohup`) is refused, and so is a wrapped interpreter that reads its
   program from stdin (`python3 -`, a here-document), because nothing on disk then shows
   what ran.
2. No command, foreground or background, may detach work from the session itself: a lone
   `&` operator, or `nohup`, `setsid`, `disown` or `daemonize` as a program, including
   inside the string an `sh`, `bash` or `zsh` runs with `-c`. A command shlex cannot parse
   falls back to a plain scan for a lone `&`.

Quoted text, `&&`, `2>&1`, `&>` and here-document bodies never count. A command longer than
MAX_COMMAND characters is not read. Exit 2 with the reason on stderr to refuse; exit 0
otherwise, including on any error of its own. This guards the honest case: an alias, a
variable, `eval` or a script file that detaches is not seen, and the reaper reports what
gets through.
"""
from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from pathlib import Path

MAX_TIMEOUT = 7200          # Claude Code's own ceiling for unattended background commands
MAX_GRACE = 60
MAX_COMMAND = 32_000
DETACHERS = {"nohup", "setsid", "disown", "daemonize"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LONE_AMP = re.compile(r"(^|[^&|>0-9])&($|[^&>])")
SUBSTITUTION = re.compile(r"\$\(|`|[<>]\(")
SINGLE_QUOTED = re.compile(r"'[^']*'")
INTERPRETERS = re.compile(r"^(python[0-9.]*|node|bun|deno|ruby|perl|bash|sh|zsh|osascript)$")
PYTHON = re.compile(r"^python[0-9.]*$")
FORM = "python3 ~/.claude/hooks/procguard.py --timeout <seconds, at most 7200> -- <command>"

REASON_FORM = (
    "Blocked: a background command must run under the process guard, which stops it and "
    "everything it started at its time limit or when this session goes away. Run it as:\n"
    f"  {FORM}\n"
    "with the shortest timeout that fits the work. {detail}"
)
REASON_DETACH = (
    "Blocked: `{what}` detaches work from this session, so nothing would stop it or report "
    "it. Use the Bash tool's run_in_background with the process guard instead:\n"
    f"  {FORM}"
)


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tokens(command: str) -> list[str]:
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace_split = True
    lex.whitespace = lex.whitespace.replace("\n", "")
    return list(lex)


def detacher(text: str, segments, depth: int = 0) -> str:
    """The first token that detaches work, or ''. A command shlex cannot parse
    (bash's $'...' quoting, say) falls back to a plain scan for a lone `&`,
    which may over-match inside quotes but never under-matches. The string a
    shell runs with -c is checked the same way, two levels deep."""
    try:
        # shlex keeps runs of punctuation together, so `(cmd &)` yields `&)`: test each
        # punctuation token for a lone `&` rather than the bare token only.
        if any(LONE_AMP.search(t) for t in tokens(text) if not t.strip(";&|()<>\n")):
            return "&"
    except ValueError:
        if LONE_AMP.search(text):
            return "&"
    for words in segments(text):
        own = [w for w in words if not ASSIGNMENT.match(w)]
        if not own:
            continue
        prog = own[0].rsplit("/", 1)[-1]
        if prog in DETACHERS:
            return prog
        if prog in SHELLS and "-c" in own[1:-1] and depth < 2:
            inner = detacher(own[own.index("-c") + 1], segments, depth + 1)
            if inner:
                return inner
    return ""


def guarded(text: str, segments, raw: str) -> str:
    """'' when the background command is one well-formed procguard call, else the problem."""
    segs = segments(text)
    if not segs:
        return "The command is empty."
    if SUBSTITUTION.search(SINGLE_QUOTED.sub("", text)):
        return ("A `$(...)`, backtick or `<(...)`/`>(...)` substitution runs in the outer shell "
                "outside the guard, with no time limit; compute the value first or move it into a script.")
    *before, last = segs
    for words in before:
        if words[:1] != ["cd"]:
            return "Only `cd <dir>` steps may come before the procguard call."
    if len(last) < 2 or not PYTHON.match(last[0].rsplit("/", 1)[-1]) or not is_procguard(last[1]):
        return "The command does not start with the procguard call."
    if "--" not in last:
        return "The wrapped command must follow `--`."
    split = last.index("--")
    opts, wrapped = last[2:split], last[split + 1:]
    # Exactly `--timeout N`, optionally `--grace N`, each once: procguard refuses
    # abbreviations and repeats too, so what is read here is what runs.
    values: dict[str, float] = {}
    i = 0
    while i < len(opts):
        name = opts[i]
        if name not in ("--timeout", "--grace") or name in values or i + 1 >= len(opts):
            return "Only `--timeout <seconds>` and `--grace <seconds>` may come before `--`, each once."
        try:
            values[name] = float(opts[i + 1])
        except ValueError:
            return f"{name} must be a number of seconds."
        i += 2
    if "--timeout" not in values:
        return "It has no --timeout."
    if not 0 < values["--timeout"] <= MAX_TIMEOUT:
        return f"--timeout must be between 1 and {MAX_TIMEOUT} seconds."
    if not 0 <= values.get("--grace", 0) <= MAX_GRACE:
        return f"--grace must be between 0 and {MAX_GRACE} seconds."
    if not wrapped:
        return "Nothing follows `--`."
    own = [w for w in wrapped if not ASSIGNMENT.match(w)] or wrapped
    prog = own[0].rsplit("/", 1)[-1]
    if prog in DETACHERS or (prog == "env" and any(w.rsplit("/", 1)[-1] in DETACHERS for w in own[1:])):
        return f"`{prog}` would move the work out of the guarded process group."
    if INTERPRETERS.match(prog) and ("-" in wrapped[1:] or "<<" in raw):
        return ("Write the program to a file in the session scratchpad and run that file, so "
                "what ran stays on disk; an interpreter reading its program from stdin is refused.")
    return ""


def is_procguard(path: str) -> bool:
    """True when `path` is this station's procguard, by content: a copy in a
    skill folder counts, a different file that only shares the name does not. A
    relative path is refused: it would resolve against this hook's directory, not
    the command's `cd` target, so the file checked could differ from the one run."""
    if not path.startswith(("/", "~/")):
        return False
    try:
        theirs = Path(path).expanduser().resolve().read_bytes()
        mine = Path(__file__).with_name("procguard.py").read_bytes()
    except OSError:
        return False
    return theirs == mine


def check(command: str, background: bool) -> str:
    if not command:
        return ""
    if len(command) > MAX_COMMAND:
        # Too long to parse in the hook's budget: a foreground command passes, a
        # background one is refused rather than run unchecked.
        return REASON_FORM.format(detail="The command is too long to check.") if background else ""
    text = sibling("deny_debugger_attach").without_heredocs(command)
    segments = sibling("guard_git_bypass").segments
    what = detacher(text, segments)
    if what:
        return REASON_DETACH.format(what=what)
    if background:
        problem = guarded(text, segments, command)
        if problem:
            return REASON_FORM.format(detail=problem)
    return ""


def main() -> int:
    ev = sibling("_input").read_event()
    if ev.tool_class != "shell" or not ev.command:
        return 0
    tool_input = (ev.raw or {}).get("tool_input") or {}
    reason = check(ev.command, bool(tool_input.get("run_in_background")))
    if not reason:
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # never brick the shell on a bug here
        print(f"background_guard error, command allowed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

#!/usr/bin/env python3
"""The folder each part of a shell command runs in, shared by warn_cross_repo_git.py and warn_foreign_edits.py.

walk(command, cwd) splits a command on `&&`, `||`, `;`, `|` and newlines, drops leading prefixes
(sudo, env, command, nohup, time, rtk, proxy) and variable assignments, and yields each simple
command's words with the folder it runs in; a `cd` moves the folder for the segments after it.
git_target(words, folder) resolves the folder a git call acts on from `-C` (repeatable, each relative
to the last), `--work-tree` and `--git-dir`, and returns it with the index of the git subcommand.

A folder held in a variable or reached through `bash -c` is not seen: this is the honest-case
reading, not a sandbox. Stdlib only.
"""
import os
import re
import shlex
from pathlib import Path

SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
PREFIXES = {"sudo", "env", "command", "nohup", "time", "rtk", "proxy"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def walk(command: str, cwd: str):
    """Yield (words, folder) for every simple command in `command`, started from `cwd`."""
    here = cwd or os.getcwd()
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
        yield words, here


def git_target(words: list[str], here: str) -> tuple[str, int]:
    """For a git call's words, the folder it acts on and the index of its subcommand."""
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
    return where, i

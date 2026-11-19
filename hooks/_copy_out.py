#!/usr/bin/env python3
"""Refuse a shell command that carries a file out of a temp root, for deny-bash-file-writes.sh.

Shell writes may land in /tmp, /private/tmp or macOS's /var/folders/<a>/<b>/T. Moving such content
to a path outside those roots is the same as writing that path from the shell, so it is refused for
cp, mv, install, rsync, ditto, ln (and gcp, gmv), tar or bsdtar extracting, unzip, cpio, pax, patch
and git apply. Planting a link in temp that points outside it is refused too, as is copying onto a
temp path that is a link, because the write goes through to the link's target.

The command is tokenized once with shell quoting, so a quoted ";" or "cp" stays data. A copier is
found anywhere in a segment, not only as its first word, so prefixes, `find -exec`, `xargs`,
`if ...; then` and subshells are covered; when the command starts nested code (`bash -c`, `eval`,
`$(...)`, backticks, `source`), the same check runs over its text with the quotes removed.

A source counts as temp when it resolves into a temp root or cannot be resolved: a variable, a
glob, stdin (`-`, /dev/stdin, /dev/fd/N, `<(...)`, a pipe), an operand fed by `find` or `xargs`, or
a folder reached through such a `cd`. A destination counts as outside unless its real path is in a
temp root and it is neither a symlink nor a hard link. A command that does not tokenize is refused
when it names one of the commands. Reads the hook payload on stdin and prints a reason on a
refusal, nothing otherwise. Stdlib only, Python 3.9. Out of reach of any text check: a program
that writes files itself (a script run by an interpreter) and text decoded at run time.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

COPIERS = {"cp", "gcp", "mv", "gmv", "install", "rsync", "ditto", "ln"}
EXTRACTORS = {"tar", "gtar", "bsdtar", "unzip", "cpio", "pax"}
PATCHERS = {"patch"}
ALL = COPIERS | EXTRACTORS | PATCHERS | {"apply"}
# Options that take a value, per command, so the value is not read as a path operand.
VALUE_FLAGS = {
    "install": {"-m", "--mode", "-o", "--owner", "-g", "--group", "-B", "-S", "--suffix"},
    "rsync": {"-e", "--rsh", "-f", "--filter", "--exclude", "--include", "--exclude-from", "--include-from"},
    "unzip": {"-P", "-x"},
    "patch": {"-p", "-F", "-B", "-r", "-z", "-V"},
}
for _name in ("cp", "gcp", "mv", "gmv", "ln", "ditto"):
    VALUE_FLAGS[_name] = {"-S", "--suffix"}
TEMP = re.compile(r"^(/private)?/tmp(/|$)|^(/private)?/var/folders/[^/]+/[^/]+/T(/|$)")
UNRESOLVED = re.compile(r"[$`*?\[{]")
STDIN = re.compile(r"^(-|/dev/stdin|/dev/fd/\d+|<\(.*)$")
REDIRECT = re.compile(r"^\d*(>>?|<<?<?|<>|>&|&>>?)")
SHELLS = r"(?:bash|sh|zsh|dash|ksh|fish)"
NESTED = re.compile(
    r"(^|[^A-Za-z0-9_.-])(\S*/)?" + SHELLS + r"(\s+--?[A-Za-z-]+)*\s+-[A-Za-z]*c(\s|$)"
    r"|(^|[;&|(`\s])(eval|source|\.)(\s|$)|\$\(|`|\$\{?SHELL\b")
HEREDOC = re.compile(r"(<<-?[ \t]*([\"']?)([A-Za-z_]\w*)\2[^\n]*\n)(.*?)(\n[ \t]*\3\b[^\n]*)", re.S)
READS_STDIN = re.compile(r"\|\s*(\S*/)?" + SHELLS + r"(\s|$)|(^|[;&|(`\s])(\S*/)?" + SHELLS + r"(\s+--?[A-Za-z-]+)*\s*<")


def resolve(path: str, here: str | None) -> str | None:
    """The real absolute path, or None when it cannot be known before the command runs."""
    if here is None or STDIN.match(path):
        return None
    path = os.path.expanduser(path)
    if UNRESOLVED.search(path) or path.startswith("~"):
        return None
    return os.path.realpath(os.path.join(here, path))


def is_temp(real: str | None) -> bool:
    return real is not None and bool(TEMP.match(real)) and "/tmp/claude-" not in real


def safe_dest(dest: str, here: str | None) -> bool:
    """A destination is safe only when it resolves into temp and is not itself a link."""
    real = resolve(dest, here)
    if not is_temp(real):
        return False
    literal = os.path.join(here or "", os.path.expanduser(dest))
    if os.path.islink(literal):
        return False
    return not (os.path.isfile(real) and os.stat(real).st_nlink > 1)


def segments(text: str):
    """Split a command into segments of words on ; | & && || and newlines, honoring quotes."""
    lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=";|")
    lex.whitespace_split = True
    lex.commenters = ""
    seg: list[str] = []
    for word in lex:
        if word in ("&&", "&") or (word and set(word) <= set(";|")):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(word)
    if seg:
        yield seg


def split_redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """Drop redirections from a command's words; return the rest and any input-redirect sources."""
    rest, inputs, i = [], [], 0
    while i < len(words):
        w = words[i]
        m = REDIRECT.match(w)
        if m and not w.startswith("<("):
            target = w[m.end():] or (words[i + 1] if i + 1 < len(words) else "")
            if m.group(1).startswith("<"):
                inputs.append("-" if m.group(1) in ("<<", "<<<") else target)
            i += 1 if w[m.end():] else 2
            continue
        rest.append(w)
        i += 1
    return rest, inputs


def operands(name: str, args: list[str]) -> tuple[list[str], str | None]:
    """Sources and destination of a copier (-t / --target-directory aware)."""
    flags = VALUE_FLAGS.get(name, set())
    plain, target, i = [], None, 0
    while i < len(args):
        w = args[i]
        if w in ("-t", "--target-directory"):
            target = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if w.startswith("--target-directory="):
            target = w.split("=", 1)[1]
        elif w in flags:
            i += 1
        elif w == "--":
            plain.extend(args[i + 1:])
            break
        elif not w.startswith("-") or STDIN.match(w):
            plain.append(w)
        i += 1
    if target is not None:
        return plain, target
    if len(plain) < 2:
        return plain, None
    return plain[:-1], plain[-1]


def extraction(name: str, args: list[str], inputs: list[str]) -> tuple[list[str], str]:
    """Archive or patch sources and the folder they land in ('.' when unnamed)."""
    dest, sources, i = ".", [], 0
    flags = VALUE_FLAGS.get(name, set())
    if name in ("tar", "gtar", "bsdtar"):
        mode = args[0] if args and not args[0].startswith("-") else ""
        if not (any(w in ("--extract", "--get") or re.match(r"^-[a-zA-Z]*x[a-zA-Z]*$", w) for w in args)
                or "x" in mode):
            return [], dest
    while i < len(args):
        w = args[i]
        if w in ("-C", "--directory", "-d") and i + 1 < len(args):
            dest = args[i + 1]
            i += 2
            continue
        if w.startswith("--directory="):
            dest = w.split("=", 1)[1]
        elif w in ("-f", "--file", "-i", "--input") and i + 1 < len(args):
            sources.append(args[i + 1])
            i += 2
            continue
        elif name in ("tar", "gtar", "bsdtar") and re.match(r"^-?[a-zA-Z]*f$", w) and i + 1 < len(args):
            sources.append(args[i + 1])
            i += 2
            continue
        elif w in flags:
            i += 1
        elif not w.startswith("-") and name in ("unzip", "patch", "apply") and not sources:
            sources.append(w)
        elif not w.startswith("-") and name in ("cpio", "pax"):
            dest = w
        i += 1
    return sources or inputs or ["-"], dest


def check_segment(words: list[str], here: str | None) -> str:
    words, inputs = split_redirects(words)
    fed = False
    for i, raw in enumerate(words):
        word = raw.lstrip("({!").rstrip(")}")
        name = os.path.basename(word)
        if name in ("find", "xargs", "parallel"):
            fed = True
        if name not in ALL or (name == "apply" and (i == 0 or os.path.basename(words[i - 1]) != "git")):
            continue
        args = [a.rstrip(")") for a in words[i + 1:]]
        if name in COPIERS:
            sources, dest = operands(name, args)
            if dest is None:
                continue
            if name == "ln" and safe_dest(dest, here):
                for src in sources:
                    if not is_temp(resolve(src, here)):
                        return f"ln plants a link in the temp folder to {src}, outside it"
                continue
        else:
            sources, dest = extraction(name, args, inputs)
            if not sources:
                continue
        if safe_dest(dest, here):
            continue
        for src in sources:
            real = None if fed else resolve(src, here)
            if real is None or is_temp(real):
                return f"{name} carries {src} from the temp folder or an unknown source to {dest}"
    return ""


def refusal_in(text: str, cwd: str) -> str:
    here: str | None = cwd
    for words in segments(text):
        head = os.path.basename(words[0].lstrip("({"))
        if head in ("cd", "pushd"):
            dest = words[1] if len(words) > 1 else "~"
            dest = os.path.expanduser(dest)
            here = None if here is None or UNRESOLVED.search(dest) or dest.startswith("-") \
                else os.path.realpath(os.path.join(here, dest))
            continue
        reason = check_segment(words, here)
        if reason:
            return reason
    return ""


def refusal(command: str, cwd: str) -> str:
    if not re.search(r"(^|[^A-Za-z0-9_-])(" + "|".join(sorted(ALL)) + r")([^A-Za-z0-9_-]|$)", command):
        return ""
    texts = [command]
    if NESTED.search(command):
        body = command if READS_STDIN.search(command) else HEREDOC.sub(r"\1", command)
        texts.append(re.sub(r"\\(.)", r"\1", body).replace('"', " ").replace("'", " ")
                     .replace("$(", " ; ").replace("`", " ; ").replace(")", " ; "))
    for text in texts:
        try:
            reason = refusal_in(text, cwd)
        except ValueError:
            return "a command naming a copy, extract or patch tool that does not tokenize cannot be checked"
        if reason:
            return reason
    return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool_input = payload.get("tool_input") or {}
        reason = refusal(str(tool_input.get("command") or ""), str(payload.get("cwd") or os.getcwd()))
    except Exception:  # noqa: BLE001 - a guard that cannot read its input refuses
        reason = "the copy check could not read the command"
    if reason:
        print(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())

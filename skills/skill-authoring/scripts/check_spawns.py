#!/usr/bin/env python3
"""Spawn lint for the house process-lifecycle standard (references/process-lifecycle.md).

    python3 check_spawns.py [paths...]            # lint; exit 1 on any finding
    python3 check_spawns.py --inventory [paths...] # every spawn site, one line each
    python3 check_spawns.py --changed <git-range>  # lint only files changed in a range

With no paths it scans the git-tracked files of the repo that holds the current
directory. Rules:

  no-timeout  subprocess.run/call/check_call/check_output without timeout=
  raw-popen   subprocess.Popen outside procguard (use procguard.popen)
  agent-cli   an agent CLI or model runner started without procguard
  os-spawn    os.system, os.popen or os.spawn* (use procguard.run)
  async-raw   asyncio.create_subprocess_* whose argv is not procguard.wrap(...)
  shell-bg    a shell line that backgrounds work (&, nohup, setsid, disown)
  shell-agent a shell line that starts an agent CLI without procguard.py

A site that must stay as written takes `# procguard: exempt <reason>` on its line
or in the comment block right above it. Test files may use Popen, start fakes directly and omit
timeouts, since a hung test blocks the suite where it is seen; the inventory
still lists those sites. Fixture trees are corpora, never run, and are skipped.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

AGENT_RE = re.compile(r"\b(claude|codex|cursor-agent|agy|gemini|opencode|ollama|cli_path|fake_bin)\b")
EXEMPT_RE = re.compile(r"#\s*procguard:\s*exempt\b")
RUN_FUNCS = {"run", "call", "check_call", "check_output"}
OS_FUNCS = {"system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
            "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp"}
SHELL_BG_RE = re.compile(r"(^|[^&|>])&\s*($|#|;|\))|\bnohup\b|\bsetsid\b|\bdisown\b")
SHELL_AGENT_RE = re.compile(r"\b(claude\s+(-p|--print)\b|codex\s+exec\b|cursor-agent\b|gemini\s+-p\b|ollama\s+run\b)")
SKIP_PARTS = {"skills-archive", "__archive", "fixtures", "node_modules", ".git"}


def is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_") or path.name.startswith("fake")


def exempt(lines: list[str], lineno: int) -> bool:
    """The marker on the line itself, or anywhere in the comment block right above it."""
    if 0 < lineno <= len(lines) and EXEMPT_RE.search(lines[lineno - 1]):
        return True
    i = lineno - 2
    while i >= 0 and lines[i].lstrip().startswith("#"):
        if EXEMPT_RE.search(lines[i]):
            return True
        i -= 1
    return False


def _owner_and_name(func: ast.AST) -> tuple[str, str]:
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else ""
        return owner, func.attr
    if isinstance(func, ast.Name):
        return "", func.id
    return "", ""


def scan_python(path: Path, text: str) -> list[tuple[int, str, str]]:
    """(line, rule or 'ok:<kind>', detail) for every spawn site in one file."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    test = is_test(path)
    guard = path.name == "procguard.py"
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        owner, name = _owner_and_name(node.func)
        kws = {k.arg for k in node.keywords}
        argsrc = ast.get_source_segment(text, node.args[0]) if node.args else ""
        argsrc = argsrc or ""
        line = node.lineno
        if owner == "procguard" and name in {"run", "popen", "wrap"}:
            sites.append((line, "ok:procguard", f"procguard.{name}"))
            continue
        if owner == "subprocess" and name in RUN_FUNCS:
            agent = bool(AGENT_RE.search(argsrc))
            if "timeout" not in kws:
                # A hung test blocks the suite in the foreground, where it is seen;
                # it is listed in the inventory but is not a finding.
                rule = "ok:test-no-timeout" if test else "no-timeout"
            elif agent and not test:
                rule = "agent-cli"
            else:
                rule = "ok:short"
            sites.append((line, rule, f"subprocess.{name}({argsrc[:60]})"))
        elif owner == "subprocess" and name == "Popen":
            rule = "ok:guard-internal" if guard or test else "raw-popen"
            sites.append((line, rule, f"subprocess.Popen({argsrc[:60]})"))
        elif owner == "os" and name in OS_FUNCS:
            sites.append((line, "os-spawn", f"os.{name}"))
        elif owner == "asyncio" and name in {"create_subprocess_exec", "create_subprocess_shell"}:
            whole = ast.get_source_segment(text, node) or ""
            rule = "ok:procguard" if "wrap(" in whole and "start_new_session" in kws else "async-raw"
            sites.append((line, rule, f"asyncio.{name}"))
    out = []
    for line, rule, detail in sites:
        if not rule.startswith("ok:") and exempt(lines, line):
            rule = "ok:exempt"
        out.append((line, rule, detail))
    return out


def scan_shell(path: Path, text: str) -> list[tuple[int, str, str]]:
    lines = text.splitlines()
    out = []
    for i, raw in enumerate(lines, 1):
        code = raw.split("#", 1)[0] if not raw.lstrip().startswith("#!") else ""
        if not code.strip():
            continue
        rule = ""
        if SHELL_AGENT_RE.search(code) and "procguard.py" not in code:
            rule = "shell-agent"
        elif SHELL_BG_RE.search(code) and "procguard.py" not in code:
            rule = "shell-bg"
        elif SHELL_AGENT_RE.search(code):
            rule = "ok:procguard"
        if rule:
            if not rule.startswith("ok:") and exempt(lines, i):
                rule = "ok:exempt"
            out.append((i, rule, code.strip()[:80]))
    return out


def tracked(root: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True,
                         timeout=60, check=True).stdout.split("\n")
    return [root / p for p in out if p]


def changed(root: Path, rng: str) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--diff-filter=AM", rng],
                         capture_output=True, text=True, timeout=60, check=True).stdout.split("\n")
    return [root / p for p in out if p]


def candidates(paths: list[Path]) -> list[Path]:
    keep = []
    for p in paths:
        if any(part in SKIP_PARTS or part.startswith("fixture") for part in p.parts) or not p.is_file():
            continue
        if p.suffix in {".py", ".sh"} or (p.suffix == "" and _shebang(p)):
            keep.append(p)
    return keep


def _shebang(p: Path) -> str:
    try:
        with p.open("rb") as f:
            head = f.readline(200).decode("utf-8", "replace")
    except OSError:
        return ""
    return head if head.startswith("#!") and ("sh" in head or "python" in head) else ""


def scan(path: Path) -> list[tuple[int, str, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    head = _shebang(path)
    if path.suffix == ".py" or "python" in head:
        return scan_python(path, text)
    return scan_shell(path, text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--inventory", action="store_true", help="list every spawn site instead of only findings")
    ap.add_argument("--changed", metavar="RANGE", help="lint files added or modified in a git range")
    a = ap.parse_args(argv)
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                               timeout=30, check=True).stdout.strip())
    if a.changed:
        files = changed(root, a.changed)
    elif a.paths:
        files = []
        for p in a.paths:
            p = p.resolve()
            files.extend(sorted(q for q in p.rglob("*") if q.is_file()) if p.is_dir() else [p])
    else:
        files = tracked(root)
    findings = 0
    for path in candidates(files):
        rel = path.relative_to(root) if root in path.parents else path
        for line, rule, detail in scan(path):
            bad = not rule.startswith("ok:")
            findings += bad
            if a.inventory or bad:
                print(f"{rel}:{line}\t{rule}\t{detail}")
    if not a.inventory:
        print(f"{findings} spawn finding(s)" if findings else "spawns ok", file=sys.stderr)
    return 1 if findings and not a.inventory else 0


if __name__ == "__main__":
    sys.exit(main())

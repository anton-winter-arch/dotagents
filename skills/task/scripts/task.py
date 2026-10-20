#!/usr/bin/env python3
"""task - one entry point for handing a bounded task to an external harness.

  task.py run <harness> <that harness's run flags> [--skill <name>...]
  task.py apply [<harness>] --run <run-id> [--force-base] [--force]
  task.py clean [<harness>] [--run <id> | --all | --older-than-days N]
  task.py tryout <run|table|tasks|versions|clean> ...

Harnesses: codex, cursor, antigravity.

`tryout` benchmarks a harness that is not an adapter yet on a fixed coding battery; it is
tryout/scripts/harness_bench.py, which takes every remaining argument.

Each harness keeps its own script under harnesses/<harness>/scripts/, with its own flags,
defaults, exit codes, state folder and isolation. This file only routes. `run` hands every
remaining argument to the named harness's script. `apply` finds the harness that owns the
run id. `clean` with no harness and no run id cleans every harness in turn.

`--skill <name>` (repeatable) appends that skill's SKILL.md to the brief, so the harness
follows it; the combined brief goes to the harness script in place of the original.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Tools only Claude Code has. A preloaded skill that leans on one cannot be followed as written.
CLAUDE_ONLY_TOOLS = re.compile(r"\b(AskUserQuestion|TaskCreate|TaskUpdate|subagent_type|SendMessage)\b"
                               r"|\b(Agent|Skill) tool\b")
BRIEF_MAX_AGE_S = 24 * 3600

# harness -> (script file, state-folder override variable, default state-folder name)
HARNESSES = {
    "codex": ("codex_task.py", "CODEX_TASK_STATE", "codex-task"),
    "cursor": ("cursor_task.py", "CURSOR_TASK_STATE", "cursor-task"),
    "antigravity": ("antigravity_task.py", "ANTIGRAVITY_TASK_STATE", "antigravity-task"),
}
TRYOUT = SKILL_DIR / "tryout" / "scripts" / "harness_bench.py"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXIT_USAGE = 2


class UsageError(Exception):
    pass


def script(harness: str) -> Path:
    return SKILL_DIR / "harnesses" / harness / "scripts" / HARNESSES[harness][0]


def state_root(harness: str) -> Path:
    """The same resolution each harness script uses for its own state folder."""
    _, env, name = HARNESSES[harness]
    raw = os.environ.get(env) or os.path.join(
        os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), name)
    return Path(raw).expanduser()


def run_id_of(args: list[str]) -> str | None:
    # The harness's argparse keeps the last --run, so routing on the first of two would
    # send one run's id to another run's harness.
    found = []
    for i, a in enumerate(args):
        if a == "--run" and i + 1 < len(args):
            found.append(args[i + 1])
        elif a.startswith("--run="):
            found.append(a.split("=", 1)[1])
    if len(found) > 1:
        raise UsageError("--run given more than once")
    return found[0] if found else None


def owner_of(args: list[str], verb: str) -> str:
    run_id = run_id_of(args)
    if run_id is None:
        raise UsageError(f"{verb} needs --run <run-id>")
    if not RUN_ID_RE.fullmatch(run_id):
        raise UsageError(f"not a run id: {run_id!r}")
    found = [h for h in HARNESSES if (state_root(h) / run_id).is_dir()]
    if not found:
        roots = ", ".join(str(state_root(h)) for h in HARNESSES)
        raise UsageError(f"no harness has a run {run_id!r} (looked in {roots})")
    if len(found) > 1:
        raise UsageError(f"run {run_id!r} exists for {' and '.join(found)}; "
                         f"name the harness: task.py {verb} <harness> --run {run_id}")
    return found[0]


def test_mode() -> bool:
    """The explicit opt-in under which the skills-root override is honored, so a stray
    export cannot swap which skills a real run preloads."""
    return os.environ.get("TASK_TEST") == "1"


def skills_root() -> Path:
    override = os.environ.get("TASK_SKILLS_ROOT") if test_mode() else None
    return Path(override).resolve() if override else SKILL_DIR.parent


def briefs_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base).expanduser() / "task" / "briefs"


def ensure_private_dir(path: Path) -> None:
    """Create `path` and its `task` parent as this user's own folders. A link, a folder
    another user owns, or one others can write to would let someone swap the brief
    between this write and the harness's read, so each is refused or tightened."""
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    for d in (path.parent, path):
        try:
            d.mkdir(exist_ok=True, mode=0o700)
        except FileExistsError:
            pass  # a file or a link to one; lstat below names it
        st = os.lstat(d)
        if not stat.S_ISDIR(st.st_mode):
            raise UsageError(f"{d} is not a real folder (a link or a file is in its place)")
        if st.st_uid != os.getuid():
            raise UsageError(f"{d} belongs to another user")
        if st.st_mode & 0o077:
            os.chmod(d, 0o700)


def take_option(args: list[str], name: str) -> tuple[list[str], list[str]]:
    """Every value of `name` (as `--name v` or `--name=v`) and the args without them."""
    values, rest, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == name:
            if i + 1 >= len(args):
                raise UsageError(f"{name} needs a value")
            values.append(args[i + 1])
            i += 2
            continue
        if a.startswith(name + "="):
            values.append(a.split("=", 1)[1])
        else:
            rest.append(a)
        i += 1
    return values, rest


def load_skill(name: str) -> tuple[Path, str]:
    if not SKILL_NAME_RE.fullmatch(name):
        raise UsageError(f"not a skill name: {name!r}")
    if name == "task":
        raise UsageError("the task skill cannot preload itself")
    root = skills_root().resolve()
    path = (root / name / "SKILL.md").resolve()
    if path.parent.parent != root:
        raise UsageError(f"skill {name!r} resolves outside {root}")
    if not path.is_file():
        raise UsageError(f"no skill {name!r} under {root}")
    return path.parent, path.read_text(encoding="utf-8")


def skill_section(name: str, folder: Path, text: str) -> str:
    return (f"\n\n## Skill to follow: {name}\n\n"
            f"The `{name}` skill follows in full. Follow it for this task where it applies. "
            "Where it conflicts with the rules of this brief (the allowlist, read-only mode, no "
            "network), those rules win. Its folder is "
            f"`{folder}`; read its references there when it points to them.\n\n"
            f"<skill name=\"{name}\">\n{text.rstrip()}\n</skill>\n")


def preload_skills(args: list[str]) -> list[str]:
    """Resolve --skill names, append each SKILL.md to the brief, and point --brief at the
    combined file. Returns the args for the harness script."""
    names, args = take_option(args, "--skill")
    if not names:
        return args
    briefs, args = take_option(args, "--brief")
    if len(briefs) != 1:
        raise UsageError("--skill needs exactly one --brief to add the skill to")
    src = briefs[0]
    try:
        brief = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise UsageError(f"cannot read the brief {src!r}: {e}")
    for name in dict.fromkeys(names):
        folder, text = load_skill(name)
        tools = sorted({m.group(0) for m in CLAUDE_ONLY_TOOLS.finditer(text)})
        if tools:
            print(f"task: warning: skill {name!r} names Claude Code-only tools ({', '.join(tools)}); "
                  "the harness has no such tool, so those steps cannot run as written", file=sys.stderr)
        brief += skill_section(name, folder, text)
    out_dir = briefs_dir()
    ensure_private_dir(out_dir)
    now = time.time()
    for old in out_dir.glob("brief-*.md"):
        try:
            st = old.lstat()
            if stat.S_ISREG(st.st_mode) and now - st.st_mtime > BRIEF_MAX_AGE_S:
                old.unlink()
        except OSError:
            continue
    out = out_dir / f"brief-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}.md"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(brief)
    return [*args, "--brief", str(out)]


def exec_harness(harness: str, args: list[str]) -> None:
    """Replace this process with the harness script, so its stdin, exit code and signal
    handling are exactly what they are when it is called directly."""
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, str(script(harness)), *args])


def clean_all(args: list[str]) -> int:
    worst = 0
    for harness in HARNESSES:
        print(f"== {harness}", flush=True)
        rc = subprocess.run([sys.executable, str(script(harness)), "clean", *args]).returncode
        worst = max(worst, rc)
    return worst


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else EXIT_USAGE
    cmd, rest = argv[0], argv[1:]
    if cmd == "tryout":
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, str(TRYOUT), *rest])
    harness = rest[0] if rest and rest[0] in HARNESSES else None
    args = rest[1:] if harness else rest
    if cmd == "run":
        if harness is None:
            given = f" (got {rest[0]!r})" if rest else ""
            raise UsageError(f"run needs a harness first: {'|'.join(HARNESSES)}{given}")
        exec_harness(harness, ["run", *preload_skills(args)])
    if cmd in ("apply", "clean"):
        if harness:
            exec_harness(harness, [cmd, *args])
        if cmd == "apply" or run_id_of(args) is not None:
            exec_harness(owner_of(args, cmd), [cmd, *args])
        return clean_all(args)
    raise UsageError(f"unknown command {cmd!r}; use run, apply, clean or tryout")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except UsageError as e:
        print(f"task: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

#!/usr/bin/env python3
"""A/B the trigger evals of a changed skill description against its committed version.

EXECUTE this after changing any model-invocable skill's description. A trigger eval's
absolute pass rate is noisy and partly structural (a vault-bound skill cannot fire when
the probe has no vault), so a single run says little. Running the old and the new
description over the same cases, at the same time and under the same model, says what
the edit changed.

    python3 trigger_ab.py deep-research obsidian            # old = HEAD, new = working tree
    python3 trigger_ab.py sanitize --base-ref origin/main --runs 3
    python3 trigger_ab.py obsidian --dry-run                  # the call count, nothing spent

For each skill it reads the description from the working tree and from --base-ref,
skips a skill whose description did not change, and runs the skill-creator plugin's
run_eval.py once per variant over the skill's evals/triggers.json. Every variant runs in
its own temporary project folder, so the throwaway skill copies never land in
~/.claude/commands and the variants can run side by side; within a variant there is one
worker, because parallel workers in one folder invoke each other's copies. The skill's
link in ~/.claude/skills is swapped for a stand-in without SKILL.md for the run, so the
probe sees only the copy under test while hooks that load the skill's scripts keep
working, and put back exactly as it was afterwards, on success, failure or interrupt.

The report lists every case whose verdict differs between the two descriptions. A case
that passed on the old description and fails on the new one is a regression, and any
regression exits 1. Full results land in ~/.local/state/skill-authoring/trigger-ab/.

Stdlib only. Spends model calls: cases x runs x 2 per skill, shown by --dry-run.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = "claude-sonnet-5"
EXIT_REGRESSION = 1
EXIT_USAGE = 2
SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")

# What a signal handler must undo: the stand-ins in place and the run_eval process groups.
ACTIVE_HIDDEN: list = []
CHILDREN: set = set()
CHILDREN_LOCK = threading.Lock()


class Usage(Exception):
    pass


def test_override(name: str) -> str | None:
    return os.environ.get(name) if os.environ.get("TRIGGER_AB_TEST") == "1" else None


def skills_link_dir() -> Path:
    return Path(test_override("TRIGGER_AB_LINK_DIR") or Path.home() / ".claude" / "skills")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "skill-authoring" / "trigger-ab"


def find_skill_creator(given: str | None) -> Path:
    if given:
        path = Path(given).expanduser()
    else:
        cache = Path.home() / ".claude" / "plugins" / "cache" / "claude-plugins-official" / "skill-creator"
        found = sorted(cache.glob("*/skills/skill-creator"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise Usage("the skill-creator plugin is not installed; "
                        "/plugin install skill-creator@claude-plugins-official, or pass --skill-creator")
        path = found[-1]
    if not (path / "scripts" / "run_eval.py").is_file():
        raise Usage(f"no scripts/run_eval.py under {path}")
    return path


def description_at(root: Path, skill: str, ref: str | None) -> str | None:
    rel = f"skills/{skill}/SKILL.md"
    if ref is None:
        path = root / rel
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
    else:
        r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{rel}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None
        text = r.stdout
    return description_of(text)


def description_of(text: str) -> str | None:
    """The frontmatter description: a plain or quoted scalar, or a folded or literal block
    joined with single spaces."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return None  # unclosed frontmatter: refuse rather than read into the body
    fm = lines[1:end]
    for i, line in enumerate(fm):
        if not line.startswith("description:"):
            continue
        value = line[len("description:"):].strip()
        if value in (">", ">-", "|", "|-"):
            block = []
            for nxt in fm[i + 1:]:
                if nxt and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
            value = " ".join(b for b in block if b)
        return value.strip("'\"") or None
    return None


def parse_output(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ValueError("run_eval printed no JSON")
    return json.loads(text[start:])


def run_variant(creator: Path, skill_dir: Path, eval_set: Path, description: str, model: str,
                runs: int, timeout: int) -> dict:
    """One run_eval call from its own throwaway project folder."""
    project = Path(tempfile.mkdtemp(prefix="trigger-ab-"))
    try:
        (project / ".claude").mkdir()
        env = dict(os.environ, PYTHONPATH=str(creator))
        cmd = [sys.executable, "-m", "scripts.run_eval", "--eval-set", str(eval_set),
               "--skill-path", str(skill_dir), "--description", description,
               "--num-workers", "1", "--runs-per-query", str(runs), "--timeout", str(timeout)]
        if model:
            cmd += ["--model", model]
        # Its own process group, so an interrupt can stop run_eval and every probe it started.
        p = subprocess.Popen(cmd, cwd=project, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        with CHILDREN_LOCK:
            CHILDREN.add(p)
        try:
            out, err = p.communicate()
        finally:
            with CHILDREN_LOCK:
                CHILDREN.discard(p)
        if p.returncode != 0:
            raise RuntimeError(f"run_eval exited {p.returncode}: {err.strip()[-400:]}")
        return parse_output(out)
    finally:
        shutil.rmtree(project, ignore_errors=True)


MARKER = ".trigger-ab-hidden"


class HiddenSkill:
    """Hide ~/.claude/skills/<skill> from Claude Code for the run without breaking what
    else reads that folder. The link is swapped for a stand-in folder that links every
    entry of the skill except SKILL.md: with no SKILL.md the skill does not register, so
    the probe sees only the copy under test, while station hooks that load the skill's
    scripts (sanitize's detect.py) keep finding them. Removing the link outright made those
    hooks skip their checks for the length of the run. The stand-in holds a marker naming
    the original link, so `restore_all` repairs it after a run that was killed. A real
    folder at that path is refused: moving the user's own files is not this tool's call."""

    def __init__(self, skill: str):
        self.path = skills_link_dir() / skill
        self.target: str | None = None

    def __enter__(self) -> "HiddenSkill":
        if not self.path.is_symlink():
            if self.path.exists():
                raise Usage(f"{self.path} is a real folder, not a link; move it aside before the run")
            return self
        self.target = os.readlink(self.path)
        source = self.path.resolve()
        self.path.unlink()
        ACTIVE_HIDDEN.append(self)
        try:
            self.path.mkdir()
            (self.path / MARKER).write_text(self.target, encoding="utf-8")
            for entry in source.iterdir():
                if entry.name != "SKILL.md":
                    (self.path / entry.name).symlink_to(entry)
        except OSError:
            self.put_back()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.put_back()

    def put_back(self) -> None:
        """Restore the link from the stand-in, or, when the swap failed before the marker
        landed, from the target this object holds. Idempotent."""
        if self.target is None:
            return
        if not restore(self.path) and not self.path.is_symlink():
            if self.path.is_dir():
                for e in self.path.iterdir():
                    if not e.is_symlink():
                        raise Usage(f"{self.path} holds real files; restore it by hand")
                    e.unlink()
                self.path.rmdir()
            if not self.path.exists():
                os.symlink(self.target, self.path)
        if self in ACTIVE_HIDDEN:
            ACTIVE_HIDDEN.remove(self)


def on_signal(signum, _frame) -> None:
    """Put every hidden skill back and stop every run_eval group, then exit. Without this a
    SIGTERM (a tool timeout) ends the process before `finally` runs, and SIGINT waits for
    the running variants before anything is restored."""
    for hidden in list(ACTIVE_HIDDEN):
        try:
            hidden.put_back()
        except Exception as e:  # noqa: BLE001 - report and keep restoring the rest
            print(f"trigger_ab: could not restore {hidden.path}: {e}", file=sys.stderr)
    with CHILDREN_LOCK:
        for p in CHILDREN:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
    print(f"trigger_ab: stopped by signal {signum}; hidden skills restored", file=sys.stderr)
    os._exit(128 + signum)


def restore(stand_in: Path) -> bool:
    """Put back the link a stand-in replaced. Only a folder holding the marker and nothing
    but links is touched, so a real folder is never removed."""
    marker = stand_in / MARKER
    if stand_in.is_symlink() or not marker.is_file():
        return False
    entries = [e for e in stand_in.iterdir() if e.name != MARKER]
    if any(not e.is_symlink() for e in entries):
        raise Usage(f"{stand_in} holds real files beside the marker; restore it by hand")
    target = marker.read_text(encoding="utf-8").strip()
    for e in entries:
        e.unlink()
    marker.unlink()
    stand_in.rmdir()
    os.symlink(target, stand_in)
    return True


def restore_all() -> list[str]:
    root = skills_link_dir()
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir()) if p.is_dir() and not p.is_symlink() and restore(p)]


def compare(base: dict, cand: dict) -> dict:
    by_query = {r["query"]: r for r in base["results"]}
    rows = []
    for r in cand["results"]:
        b = by_query.get(r["query"])
        if b is None:
            continue
        rows.append({"query": r["query"], "should_trigger": r["should_trigger"],
                     "base_pass": b["pass"], "cand_pass": r["pass"],
                     "base": f"{b['triggers']}/{b['runs']}", "cand": f"{r['triggers']}/{r['runs']}"})
    return {
        "base_passed": sum(x["base_pass"] for x in rows),
        "cand_passed": sum(x["cand_pass"] for x in rows),
        "total": len(rows),
        "regressions": [x for x in rows if x["base_pass"] and not x["cand_pass"]],
        "gains": [x for x in rows if not x["base_pass"] and x["cand_pass"]],
        "both_fail": [x for x in rows if not x["base_pass"] and not x["cand_pass"]],
    }


def report(skill: str, c: dict) -> str:
    lines = [f"## {skill}: old {c['base_passed']}/{c['total']}, new {c['cand_passed']}/{c['total']}"]
    for label, key in (("REGRESSION", "regressions"), ("gain", "gains"), ("fails on both", "both_fail")):
        for x in c[key]:
            kind = "should fire" if x["should_trigger"] else "should not fire"
            lines.append(f"- {label} ({kind}, old {x['base']}, new {x['cand']}): {x['query'][:100]}")
    if not (c["regressions"] or c["gains"] or c["both_fail"]):
        lines.append("- every case passes on both")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("skills", nargs="+")
    ap.add_argument("--base-ref", default="HEAD", help="git ref holding the old description (HEAD)")
    ap.add_argument("--runs", type=int, default=1, help="runs per case; use 3 to settle a flip")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"probe model, pinned ({DEFAULT_MODEL})")
    ap.add_argument("--timeout", type=int, default=30, help="seconds per probe")
    ap.add_argument("--jobs", type=int, default=6, help="variants run at once")
    ap.add_argument("--skill-creator", help="path to the skill-creator plugin's skill folder")
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--dry-run", action="store_true", help="print the call count and spend nothing")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    for skill in a.skills:
        if not SKILL_NAME.fullmatch(skill):
            raise Usage(f"not a skill name: {skill!r}")
    if a.base_ref.startswith("-"):
        raise Usage(f"not a git ref: {a.base_ref!r}")

    # One run per machine at a time: a second run's repair pass would restore the first
    # run's live stand-in mid-run and corrupt its results. Held until the process exits.
    state_dir().mkdir(parents=True, exist_ok=True)
    lock = open(state_dir() / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise Usage("another trigger_ab run is active on this machine; wait for it to finish")
    for name in restore_all():
        print(f"restored {skills_link_dir() / name}, left hidden by an earlier run that did not finish")

    plan = []
    for skill in dict.fromkeys(a.skills):
        new = description_at(root, skill, None)
        old = description_at(root, skill, a.base_ref)
        eval_set = root / "skills" / skill / "evals" / "triggers.json"
        if new is None:
            raise Usage(f"no skill {skill!r} with a description under {root / 'skills'}")
        if old is None:
            raise Usage(f"{skill!r} has no description at {a.base_ref}")
        if not eval_set.is_file():
            raise Usage(f"{skill!r} has no evals/triggers.json")
        if old == new:
            print(f"{skill}: description unchanged since {a.base_ref}; skipped")
            continue
        cases = len(json.loads(eval_set.read_text(encoding="utf-8")))
        plan.append((skill, old, new, eval_set, cases))
    calls = sum(cases * a.runs * 2 for *_, cases in plan)
    print(f"{len(plan)} skill(s), {calls} probe calls on {a.model}")
    if a.dry_run or not plan:
        return 0

    creator = find_skill_creator(a.skill_creator)
    out_dir = state_dir() / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    worst = 0
    links = [HiddenSkill(skill) for skill, *_ in plan]
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    try:
        for link in links:
            link.__enter__()
        with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            futures = {}
            for skill, old, new, eval_set, _ in plan:
                skill_dir = root / "skills" / skill
                for variant, desc in (("old", old), ("new", new)):
                    futures[(skill, variant)] = ex.submit(run_variant, creator, skill_dir, eval_set,
                                                          desc, a.model, a.runs, a.timeout)
            results = {key: f.result() for key, f in futures.items()}
    finally:
        for link in reversed(links):
            link.__exit__(None, None, None)
    for skill, *_ in plan:
        c = compare(results[(skill, "old")], results[(skill, "new")])
        (out_dir / f"{skill}.json").write_text(json.dumps(
            {"old": results[(skill, "old")], "new": results[(skill, "new")], "compare": c}, indent=2))
        print(report(skill, c))
        if c["regressions"]:
            worst = EXIT_REGRESSION
    print(f"full results: {out_dir}")
    return worst


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Usage as e:
        print(f"trigger_ab: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

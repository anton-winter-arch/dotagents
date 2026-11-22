#!/usr/bin/env python3
"""Measure whether a skill model-invokes, the way a real session would see it.

EXECUTE this to run a skill's evals/triggers.json; `trigger_ab.py` calls it for each
description it compares. Each probe is `claude -p` on this station, with the skill as
installed (run `sync-skills.sh` first for a new skill), in a fresh git project seeded
from the skill's evals/fixture/. The case text goes on stdin, with API-key variables
removed from the probe's environment.

Each case is scored at the point the model commits, on the main thread only: a Skill
call naming the skill, or a Read of its SKILL.md, is a hit; a Skill call naming another
skill, the first Agent/Task/Edit/Write call, an answer with no tool, or `--cap`
exploring calls is a miss. Bash, Read, Glob and Grep before that are exploration. The
probe is stopped once the case is decided.

    python3 trigger_eval.py skills/goldfish                        # 3 runs per case
    python3 trigger_eval.py skills/goldfish --runs 1 --description "New text."

`--description` writes the given text into the skill's SKILL.md for the run and puts
the original bytes back afterwards. A fixture holding .claude/, .mcp.json or a symlink
is refused, since a probe would load that config or read the link's target.

Prints run_eval's result shape (results[].query/should_trigger/triggers/runs/pass,
plus each run's verdict, reason and tool sequence) as JSON. Exit 0 when the run
completed, whatever the scores; 2 on a usage error or a probe that ran on another
model. Stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procguard  # noqa: E402
from check_descriptions import parse_description  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-5-5"
DOING = {"Agent", "Task", "Edit", "Write", "MultiEdit", "NotebookEdit"}
FIXTURE_REFUSED = (".claude", ".mcp.json")
PROBE_ENV_DROPPED = ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Probes run with no hooks, so station hooks and the memory plugin never see a case.
NO_HOOKS = json.dumps({"disableAllHooks": True})
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") \
    / "skill-authoring" / "trigger-eval"


class EvalError(Exception):
    """The run cannot produce a trustworthy number; nothing is scored."""


def description_of(text: str) -> str | None:
    return parse_description(text).text


# ---- scoring -------------------------------------------------------------------

class Scorer:
    """Reads one probe's stream-json and decides hit or miss at the commit point."""

    def __init__(self, target: str, cap: int, model: str | None):
        self.target, self.cap, self.model = target, cap, model
        self.tools: list[str] = []
        self.decision: dict | None = None

    def decide(self, verdict: str, reason: str) -> dict:
        self.decision = {"verdict": verdict, "reason": reason, "tools": list(self.tools)}
        return self.decision

    def feed_line(self, line: str) -> dict | None:
        line = line.strip()
        if not line:
            return None
        try:
            event = json.loads(line)
        except ValueError:
            if "Not logged in" in line:
                raise EvalError("claude is not logged in on this station") from None
            return None
        return self.feed(event) if isinstance(event, dict) else None

    def feed(self, event: dict) -> dict | None:
        if self.decision:
            return self.decision
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            got = event.get("model")
            if self.model and got and got != self.model:
                raise EvalError(f"the probe ran on model {got}, not the pinned {self.model}")
        if kind == "assistant" and event.get("parent_tool_use_id") is None:
            for block in (event.get("message") or {}).get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                decided = self.tool(str(block.get("name", "")), block.get("input") or {})
                if decided:
                    return decided
        if kind == "result":
            return self.finish()
        return None

    def tool(self, name: str, inp: dict) -> dict | None:
        if name == "Skill":
            skill = str(inp.get("skill", ""))
            self.tools.append(f"Skill:{skill}")
            if skill == self.target or skill.endswith(":" + self.target):
                return self.decide("hit", "skill")
            return self.decide("miss", f"sibling:{skill}")
        self.tools.append(name)
        if name == "Read" and str(inp.get("file_path", "")).endswith(f"/{self.target}/SKILL.md"):
            return self.decide("hit", "read-skill")
        if name in DOING:
            return self.decide("miss", f"did-the-work:{name}")
        if len(self.tools) >= self.cap:
            return self.decide("miss", "cap")
        return None

    def finish(self) -> dict:
        return self.decision or self.decide("miss", "answered" if not self.tools else "ended")


def score(events: list[dict], target: str, cap: int = 8, model: str | None = DEFAULT_MODEL) -> dict:
    """Score a recorded event list."""
    scorer = Scorer(target, cap, model)
    for event in events:
        if scorer.feed(event):
            break
    return scorer.finish()


# ---- the description under test -------------------------------------------------

def set_description(text: str, description: str) -> str:
    """SKILL.md text with its frontmatter description replaced by a folded block."""
    lines = text.split("\n")
    end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    for i in range(1, end):
        if lines[i].startswith("description:"):
            j = i + 1
            while j < end and (not lines[j] or lines[j][0].isspace()):
                j += 1
            lines[i:j] = ["description: >-", "  " + " ".join(description.split())]
            return "\n".join(lines)
    raise EvalError("the skill has no description to replace")


# ---- probes --------------------------------------------------------------------

def check_fixture(root: Path) -> None:
    """Refuse config a probe would load and links whose targets it would read. Names
    compare case-folded, since a case-insensitive disk finds .Claude/ as .claude/."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or name.casefold() in FIXTURE_REFUSED:
                raise EvalError(f"the fixture may not hold {path.relative_to(root)}: "
                                f"no .claude/, .mcp.json or symlinks")


def new_project(skill_dir: Path) -> Path:
    """A fresh git repo seeded from the skill's evals/fixture/, checked as copied."""
    fixture = skill_dir / "evals" / "fixture"
    project = Path(tempfile.mkdtemp(prefix="trigger-eval-"))
    try:
        if fixture.is_dir():
            shutil.copytree(fixture, project, dirs_exist_ok=True, symlinks=True)
            check_fixture(project)
        procguard.run(["git", "init", "-q"], cwd=project, timeout=30, capture_output=True)
    except BaseException:
        shutil.rmtree(project, ignore_errors=True)
        raise
    return project


def probe(query: str, skill_dir: Path, model: str, cap: int, timeout: float) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in PROBE_ENV_DROPPED}
    argv = ["claude", "-p", "--model", model, "--output-format", "stream-json",
            "--verbose", "--max-turns", str(cap + 2), "--settings", NO_HOOKS]
    scorer = Scorer(skill_dir.name, cap, model)
    project = new_project(skill_dir)
    proc = None
    try:
        proc = procguard.popen(argv, timeout=timeout, cwd=project, env=env, text=True,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
        proc.stdin.write(query)   # on stdin, so a case starting with "-" is never a flag
        proc.stdin.close()
        for line in proc.stdout:
            if scorer.feed_line(line):
                break
    finally:
        if proc is not None:
            if proc.poll() is None:
                procguard.stop(proc.pid)
            proc.wait()
            procguard.release(proc)
        shutil.rmtree(project, ignore_errors=True)
    return scorer.finish()


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.trigger-eval.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def run_eval(skill_dir: Path, cases: list[dict], *, model: str, runs: int, timeout: float,
             cap: int, description: str | None = None, jobs: int = 6) -> dict:
    """Run every case. One run per skill at a time; a variant description is written
    into SKILL.md with the original kept under STATE, so even a killed run is undone
    by the next one."""
    skill_dir = skill_dir.resolve()
    md = skill_dir / "SKILL.md"
    if md.is_symlink():
        raise EvalError(f"{md} is a link; test the file it points to")
    STATE.mkdir(parents=True, exist_ok=True)
    backup = STATE / f"{skill_dir.name}.SKILL.md.orig"
    with open(STATE / f"{skill_dir.name}.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise EvalError(f"another trigger eval is running on {skill_dir.name}") from None
        if backup.is_file():   # left by a killed run
            write_atomic(md, backup.read_bytes())
            backup.unlink()
        original = md.read_bytes()
        try:
            if description is not None:
                write_atomic(backup, original)
                write_atomic(md, set_description(original.decode("utf-8"), description).encode("utf-8"))
            tested = description_of(md.read_text(encoding="utf-8"))
            # Every probe has its own project folder, so they run side by side.
            pool = cf.ThreadPoolExecutor(max_workers=max(1, jobs))
            futures: list = []
            try:
                for case in cases:
                    futures.append([pool.submit(probe, case["query"], skill_dir, model, cap, timeout)
                                    for _ in range(runs)])
                details = [[f.result() for f in row] for row in futures]
            except BaseException:
                for f in (f for row in futures for f in row):
                    f.cancel()   # one failure ends the run instead of spending the queue
                raise
            finally:
                pool.shutdown(wait=True)
        finally:
            if md.read_bytes() != original:
                write_atomic(md, original)
            if backup.is_file():
                backup.unlink()
    results = []
    for case, detail in zip(cases, details):
        triggers = sum(d["verdict"] == "hit" for d in detail)
        rate = triggers / runs if runs else 0.0
        should = bool(case["should_trigger"])
        results.append({"query": case["query"], "should_trigger": should,
                        "trigger_rate": rate, "triggers": triggers, "runs": runs,
                        "pass": rate >= 0.5 if should else rate < 0.5, "detail": detail})
    passed = sum(r["pass"] for r in results)
    return {"skill_name": skill_dir.name, "description": tested, "model": model,
            "results": results,
            "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skill", type=Path, help="the skill folder (skills/<name>)")
    ap.add_argument("--eval-set", type=Path, help="cases (default: <skill>/evals/triggers.json)")
    ap.add_argument("--description", help="test this description instead of the skill's own")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"pinned probe model ({DEFAULT_MODEL})")
    ap.add_argument("--runs", type=int, default=3, help="runs per case (3)")
    ap.add_argument("--timeout", type=float, default=120, help="seconds per probe (120)")
    ap.add_argument("--cap", type=int, default=8, help="exploring calls before a miss (8)")
    ap.add_argument("--jobs", type=int, default=6, help="probes run at once (6)")
    a = ap.parse_args(argv)
    procguard.install_signal_handlers()
    try:
        if not (a.skill / "SKILL.md").is_file():
            raise EvalError(f"no SKILL.md in {a.skill}")
        eval_set = a.eval_set or a.skill / "evals" / "triggers.json"
        cases = json.loads(eval_set.read_text(encoding="utf-8"))
        data = run_eval(a.skill, cases, model=a.model, runs=a.runs, timeout=a.timeout,
                        cap=a.cap, description=a.description, jobs=a.jobs)
    except (EvalError, OSError, ValueError) as exc:
        print(f"trigger_eval: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

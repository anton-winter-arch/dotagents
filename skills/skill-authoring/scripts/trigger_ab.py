#!/usr/bin/env python3
"""A/B the trigger evals of a changed skill description against its committed version.

EXECUTE this after changing any model-invocable skill's description. Running the old
and the new description over the same cases, under the same model, says what the edit
changed, which one run's pass rate cannot.

    python3 trigger_ab.py deep-research obsidian            # old = HEAD, new = working tree
    python3 trigger_ab.py sanitize --base-ref origin/main --runs 3
    python3 trigger_ab.py obsidian --dry-run                  # the call count, nothing spent

For each skill it reads the description from the working tree and from --base-ref,
skips a skill whose description did not change, and runs `trigger_eval.py` once per
variant over the skill's evals/triggers.json, writing each variant's description into
the skill's SKILL.md for its run and restoring the file afterwards. Variants run one
after another.

The report lists every case whose verdict differs between the two descriptions. A case
that passed on the old description and fails on the new one is a regression, and any
regression exits 1. Full results land in ~/.local/state/skill-authoring/trigger-ab/.

At start it also repairs a skill link that an older version of this tool left hidden
behind a stand-in folder when it was killed.

Stdlib only. Spends model calls: cases x runs x 2 per skill, shown by --dry-run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import procguard  # noqa: E402
import trigger_eval as te  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = te.DEFAULT_MODEL
EXIT_REGRESSION = 1
EXIT_USAGE = 2
SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
description_of = te.description_of


class Usage(Exception):
    pass


def test_override(name: str) -> str | None:
    return os.environ.get(name) if os.environ.get("TRIGGER_AB_TEST") == "1" else None


def skills_link_dir() -> Path:
    return Path(test_override("TRIGGER_AB_LINK_DIR") or Path.home() / ".claude" / "skills")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "skill-authoring" / "trigger-ab"


def description_at(root: Path, skill: str, ref: str | None) -> str | None:
    rel = f"skills/{skill}/SKILL.md"
    if ref is None:
        path = root / rel
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
    else:
        r = procguard.run(["git", "-C", str(root), "show", f"{ref}:{rel}"],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        text = r.stdout
    return description_of(text)


# ---- repair of stand-ins left by the earlier hide-the-link design -----------------

MARKER = ".trigger-ab-hidden"


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


# ---- comparison ----------------------------------------------------------------

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
    ap.add_argument("--timeout", type=float, default=120, help="seconds per probe (120)")
    ap.add_argument("--cap", type=int, default=8, help="exploring calls before a miss (8)")
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--dry-run", action="store_true", help="print the call count and spend nothing")
    ap.add_argument("--jobs", type=int, default=6, help="probes run at once (6)")
    # Accepted for older callers; the plugin runner is gone.
    for flag in ("--skill-creator", "--variant-timeout"):
        ap.add_argument(flag, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    for skill in a.skills:
        if not SKILL_NAME.fullmatch(skill):
            raise Usage(f"not a skill name: {skill!r}")
    if a.base_ref.startswith("-"):
        raise Usage(f"not a git ref: {a.base_ref!r}")
    procguard.install_signal_handlers()
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
        cases = json.loads(eval_set.read_text(encoding="utf-8"))
        plan.append((skill, old, new, cases))
    calls = sum(len(cases) * a.runs * 2 for *_, cases in plan)
    print(f"{len(plan)} skill(s), {calls} probe calls on {a.model}")
    if a.dry_run or not plan:
        return 0

    out_dir = state_dir() / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    worst = 0
    for skill, old, new, cases in plan:
        results = {}
        for variant, desc in (("old", old), ("new", new)):
            try:
                results[variant] = te.run_eval(root / "skills" / skill, cases, model=a.model,
                                               runs=a.runs, timeout=a.timeout, cap=a.cap,
                                               description=desc, jobs=a.jobs)
            except te.EvalError as e:
                raise Usage(str(e)) from None
        c = compare(results["old"], results["new"])
        (out_dir / f"{skill}.json").write_text(json.dumps({**results, "compare": c}, indent=2))
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

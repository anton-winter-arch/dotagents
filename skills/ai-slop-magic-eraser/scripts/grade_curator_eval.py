#!/usr/bin/env python3
"""Grade a curator eval run: did every fact survive, and is the control untouched.

EXECUTE this script after the curator has edited scratch copies of the fixtures
in evals/curator/ - never run the curator on the fixtures themselves.

    python3 grade_curator_eval.py <dir holding the edited copies>

A case passes when every `must_keep` string from evals/curator/cases.json is
still in its edited file (whitespace collapsed, so a fact split across a line
wrap still counts), and the control comes back byte-identical. Whether the
rewrite is any good is judgment; read the curator's report and the diff for that.

Exit 0 every case passes, 1 any case fails, 2 a file is missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "evals" / "curator"


def missing_facts(text: str, facts: list[str]) -> list[str]:
    """The facts not present in text, comparing with whitespace collapsed."""
    flat = " ".join(text.split())
    return [fact for fact in facts if " ".join(fact.split()) not in flat]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    edited_dir = Path(argv[0])
    if edited_dir.resolve() == CASES_DIR.resolve():
        print("grade scratch copies, never the fixtures themselves", file=sys.stderr)
        return 2
    cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]

    missing = [c["file"] for c in cases if not (edited_dir / c["file"]).is_file()]
    if missing:
        print(f"missing from {edited_dir}: {', '.join(missing)}", file=sys.stderr)
        return 2

    failed = 0
    for case in cases:
        edited = (edited_dir / case["file"]).read_text(encoding="utf-8")
        problems = [f"dropped: {fact}" for fact in missing_facts(edited, case["must_keep"])]
        if case["defect"] is None:
            original = (CASES_DIR / case["file"]).read_text(encoding="utf-8")
            if edited != original:
                problems.append("control was edited")
        failed += bool(problems)
        print(f"{'FAIL' if problems else 'PASS'}  {case['file']}")
        for problem in problems:
            print(f"      {problem}")

    print(f"\n{len(cases) - failed}/{len(cases)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

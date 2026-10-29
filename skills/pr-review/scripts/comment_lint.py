#!/usr/bin/env python3
"""Lint a PR review comment against the pr-review budget and register.

Reads the **COMMENTS-DRAFT** block of one `## PR-STORY-...` section of a
notes-pr-reviews file, or a bare file. Thread labels such as
`(<file> LINES 19-26)` are not pasted, so they are dropped before linting.
Exit 0 clean, 1 findings. Stdlib only.

    python3 comment_lint.py notes-pr-reviews.md --block PR-STORY-000000-XX-2026-01-01
    python3 comment_lint.py draft.txt
"""

import argparse
import re
import sys

CLOSE = "Any questions LMK"

# fires on positive evidence: a capital letter that is not one of these shapes
ALLOWED_CAPS = re.compile(
    r"""^(?:
          [A-Z0-9_]{2,}s?               # DBT_SEEDS, ADO, SQL, ERP, PRs
        | [A-Za-z0-9_]*[._][A-Za-z0-9_.]*  # file.py, schema.table, DBT_Silver_Common
        | [A-Z]{1,3}\d*                 # initials, one to three letters
        | [0-9a-f]{7,40}                # commit hashes
        | I                             # the pronoun, tolerated
    )$""",
    re.VERBOSE,
)

SNEER = [
    r"\beven\s+(?:deploy|work|run|parse|build)\b",
    r"\bwhich i['’]?d expect\b",
    r"\bobviously\b",
    r"\bclearly\b",
    r"\bsimply\b",
    r"\bapparently\b",
    r"\bsomehow\b",
]

FACTIONAL = [
    r"\bour (?:copy|version|side|end)\b",
    r"\bone of yours\b",
    r"\bsomething of ours\b",
    r"\byours\b",
    r"\bours\b",
]

SEVERITY = [
    r"\bcritical\b",
    r"\bsevere\b",
    r"\burgent\b",
    r"\bdangerous\b",
    r"\bbroken\b",
    r"\bsilently\b",
    r"\bcorrupt\w*\b",
]


FENCE = re.compile(r"^(`{3,})(.*)$")
THREAD_LABEL = re.compile(r"^\s*\([^()\n]*\bLINES?\s+\d+(?:\s*[-,]\s*\d+)*\)\s*$")


def extract(text, block):
    """Return the **COMMENTS-DRAFT** fence of the `## <block>` section."""
    if block is None:
        return text
    in_sec = want = False
    fence = body = None
    for line in text.split("\n"):
        f = FENCE.match(line)
        if fence:
            if f and len(f.group(1)) >= len(fence) and not f.group(2).strip():
                if body is not None:
                    return "\n".join(body)
                fence = None
            elif body is not None:
                body.append(line)
            continue
        if f:
            fence = f.group(1)
            if want:
                body = []
            continue
        if re.match(r"^#{1,2} ", line):
            if in_sec:
                break
            in_sec = line.lstrip("#").strip() == block
        elif in_sec and line.strip():
            want = line.strip() == "**COMMENTS-DRAFT**"
    if body is not None:
        sys.exit(f"comment_lint: unterminated **COMMENTS-DRAFT** fence under '## {block}'")
    sys.exit(f"comment_lint: no **COMMENTS-DRAFT** block under '## {block}'")


def drop_labels(body):
    return "\n".join(l for l in body.splitlines() if not THREAD_LABEL.match(l))


def strip_code(s):
    return re.sub(r"`[^`]*`", " ", s)


def shape(body):
    """Length, reported and never gated. Reader cost is open loops, not counts."""
    prose = strip_code(body)
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    return (
        f"{len(prose.split())} words, {prose.count('?')} questions, "
        f"{len(paras)} paragraphs"
    )


def check(body):
    out = []
    prose = strip_code(body)

    for line in body.splitlines():
        if re.match(r"^\s*\d+[.)]\s+\S", line):
            out.append(f"numbered question list reads as an audit report: {line.strip()[:60]}")

    # sentence-initial capitals are normal; a capitalized ordinary word mid-sentence
    # is the tell (Title Case, or a role noun promoted to a Proper Noun).
    text = prose.replace(CLOSE, " ")
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9_.'’-]*", text):
        before = text[: m.start()].rstrip()
        if not before or before[-1] in ".?!:\n":
            continue
        tok = re.sub(r"['’]s$", "", m.group(0))
        if tok[0].isupper() and not ALLOWED_CAPS.match(tok):
            out.append(f"capitalized mid-sentence: {tok}")

    for pats, label in (
        (SNEER, "sneer"),
        (FACTIONAL, "factional pronoun"),
        (SEVERITY, "severity word"),
    ):
        for pat in pats:
            for m in re.finditer(pat, prose, re.I):
                out.append(f"{label}: {m.group(0)}")

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--block", help="the `## PR-STORY-...` section whose COMMENTS-DRAFT to lint")
    a = ap.parse_args()

    with open(a.file, encoding="utf-8") as fh:
        body = drop_labels(extract(fh.read(), a.block))
    print(shape(body))
    findings = check(body)

    seen, uniq = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            uniq.append(f)

    for f in uniq:
        print(f)
    print(f"\n{len(uniq)} finding(s)" if uniq else "clean")
    return 1 if uniq else 0


if __name__ == "__main__":
    sys.exit(main())

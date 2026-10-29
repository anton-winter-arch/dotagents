#!/usr/bin/env python3
"""PostToolUse(Write|Edit) linter for the file-based memory dirs.

Fires after a write whose path is a memory file
(~/.claude/projects/<slug>/memory/*.md) and lints that dir. Split by what is
actually verifiable:

  DETERMINISTIC -> exit 2 (blocks / returns stderr to the agent so it is fixed
  now). Footgun, verified: exit 2 returns stderr to the agent; exit 1 is
  swallowed silently. A lint that exits 1 does nothing - so failures use 2.

  JUDGMENT -> advisory, exit 0, delivered as PostToolUse additionalContext on
  stdout. Stderr at exit 0 is swallowed by the harness (the same footgun), so
  an advisory printed there reaches nobody.

Stdlib only, no network. Fails OPEN: any error in the lint itself exits 0 so a
lint bug can never block a real memory write.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

VALID_TYPES = {"user", "feedback", "project", "reference"}
# Claude Code loads the first 200 lines or 25KB of MEMORY.md. 100 memories x 220
# chars stays under 25KB with room for the header and section headings.
INDEX_LINE_CAP = 220
# Below this many words after the link, an index line is a title, not a summary.
MIN_SUMMARY_WORDS = 6


def frontmatter(text: str) -> str | None:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else None


def clean(s: str) -> str:
    """Escape control chars before echoing a captured value to the agent's
    stderr - a memory file's `name:`/`type:` is untrusted-ish and could carry
    ANSI escapes otherwise."""
    return s.encode("unicode_escape").decode("ascii", "replace")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return 0
    p = Path(fp)

    # Only memory files: <config dir>/projects/<slug>/memory/<name>.md, anchored on the
    # harness config dir so a repo folder with the same layout is never linted as
    # memory. Both sides resolve, matching memory-routing.sh on symlinks and slashes.
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    if p.suffix != ".md" or p.parent.name != "memory":
        return 0
    if p.parent.parent.resolve().parent != (root / "projects").resolve():
        return 0

    memdir = p.parent
    index = memdir / "MEMORY.md"
    try:
        index_text = index.read_text(encoding="utf-8", errors="replace") if index.exists() else ""
        mem_files = sorted(f for f in memdir.glob("*.md") if f.name != "MEMORY.md")
    except OSError:
        return 0  # can't read the dir → don't block the write

    errors: list[str] = []   # deterministic → exit 2
    warns: list[str] = []    # advisory

    if not index.exists():
        errors.append("MEMORY.md index is missing - every memory dir needs one")

    names = {f.stem for f in mem_files}
    body_all = []

    for f in mem_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body_all.append(text)
        stem = f.stem

        # Pointer in the index (unindexed memory is never recalled).
        if f.name not in index_text and stem not in index_text:
            errors.append(f"{f.name}: no pointer line in MEMORY.md (an unindexed memory is dead weight)")

        fm = frontmatter(text)
        if fm is None:
            errors.append(f"{f.name}: no YAML frontmatter")
            continue

        nm = re.search(r"(?m)^name:\s*(\S+)", fm)
        if not nm:
            errors.append(f"{f.name}: frontmatter missing `name:`")
        elif nm.group(1) != stem:
            errors.append(f"{f.name}: `name: {clean(nm.group(1))}` does not match filename stem `{stem}`")

        if not re.search(r"(?m)^description:\s*\S", fm):
            errors.append(f"{f.name}: frontmatter missing `description:`")

        tm = re.search(r"(?m)^\s*type:\s*(\S+)", fm)
        if not tm:
            errors.append(f"{f.name}: frontmatter missing `metadata.type`")
        elif tm.group(1) not in VALID_TYPES:
            errors.append(f"{f.name}: `type: {clean(tm.group(1))}` not in {sorted(VALID_TYPES)}")

    # Every index pointer resolves to a file that exists.
    for link in re.findall(r"\]\(([^)\n]{1,200}\.md)\)", index_text):
        if not (memdir / Path(link).name).exists():
            errors.append(f"MEMORY.md pointer → {link} does not resolve to a file")

    # Advisory: dangling wikilinks are ALLOWED (mark a memory worth writing later).
    # Only closed, single-line links of bounded length count, and the link text
    # is escaped and the list capped: this text now reaches the model as context,
    # and a stray `[[` must not drag a file's worth of prose into it.
    link_re = r"\[\[([^\]\|#\n]{1,120})(?:[|#][^\]\n]{0,120})?\]\]"
    dangling = sorted({wl.strip() for wl in re.findall(link_re, "".join(body_all))
                       if wl.strip() not in names})
    if dangling:
        shown = ", ".join(f"[[{clean(wl)}]]" for wl in dangling[:10])
        more = f" (+{len(dangling) - 10} more)" if len(dangling) > 10 else ""
        warns.append(f"dangling {shown}{more} - fine as forward stubs; if a memory was just "
                     "removed or merged, repoint links to it to the survivor")

    # The two index-line checks below are scoped to the line for the file just
    # written (or every line when the index itself was written), so a folder of
    # weak lines never fires on every write.
    pointer = f"]({p.name})"

    # Advisory: the index is the only memory text loaded every session, so a line
    # that is a link plus a title recalls nothing. It must say what the memory
    # holds and when to open it. Bounded like the wikilinks above.
    line_re = r"\s*[-*]\s*\[([^\]\n]{0,200})\]\(([^)\n]{1,200}\.md)\)(.*)"
    thin = []
    for ln in index_text.splitlines():
        m = re.fullmatch(line_re, ln)
        if not m or (p.name != "MEMORY.md" and Path(m.group(2)).name != p.name):
            continue
        summary = m.group(3).strip().lstrip("-:–—").strip()
        if (len(summary.split()) < MIN_SUMMARY_WORDS
                or summary.lower().rstrip(".") == m.group(1).strip().lower().rstrip(".")):
            thin.append(ln.strip())
    for ln in thin[:5]:
        warns.append(f"index line reads as a title: {clean(ln)} - say what the memory holds and when to open it")
    if len(thin) > 5:
        warns.append(f"+{len(thin) - 5} more index lines that read as titles")
    if thin:
        warns.append('"No framing openers in chat" is a title; "No framing openers in chat - start with '
                     'the first finding; applies to every reply" is an index line')

    # Advisory: the index loads every session, so each line stays under the cap.
    long_lines = [ln for ln in index_text.splitlines()
                  if len(ln) >= INDEX_LINE_CAP and (p.name == "MEMORY.md" or pointer in ln)]
    for ln in long_lines[:5]:
        stem = re.search(r"\]\(([^)\n]{1,200})\)", ln) if p.name == "MEMORY.md" else None
        label = stem.group(1) if stem else p.name
        warns.append(f"index line for {clean(label)} is {len(ln)} chars; "
                     f"keep it under {INDEX_LINE_CAP}: what the memory holds and when to open it")
    if len(long_lines) > 5:
        warns.append(f"+{len(long_lines) - 5} more index lines over {INDEX_LINE_CAP} chars")

    warns.append(
        "reconcile: does this repo's own documentation still agree with this memory? "
        "If this memory CORRECTS something, correct the doc too - a memory and a doc that disagree are worse than either alone."
    )

    if errors:
        for w in warns:
            print(f"memory-lint [advisory]: {w}", file=sys.stderr)
        for e in errors:
            print(f"memory-lint [FAIL]: {e}", file=sys.stderr)
        return 2
    # Advisory only: the verified channel at exit 0 is additionalContext.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "memory-lint [advisory]: " + " | ".join(warns),
    }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: a lint bug must never block a memory write

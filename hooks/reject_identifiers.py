#!/usr/bin/env python3
"""PreToolUse hook: surface project identifiers in NEW content written to portable files.

A skill, a certification and a research artifact all travel further than the vault they
are written in: a skill gets copied, a certification feeds a merge into canon, and git
history keeps what a later edit removes from the tree. A check that runs at publish time
therefore runs too late to help, because by then the identifier is already committed.

So the check is at the write, not at the exit. It never blocks: every hit is returned to
the model as PreToolUse `additionalContext` and the write proceeds, so the model (or the
user, in place) decides whether the value is a leak or a legitimate word. A gate that
refuses ordinary prose because a term is also a dictionary word gets muted, and a muted
gate is worse than none. The commit gate (`sanitize gate`) warns on the same content
again at commit; this is the early warning.

GUARDED PATHS (portable or canon-bound; identifiers must never enter these):
    **/.claude/skills/**      **/.agents/skills/**    ~/.claude/hooks/**
    **/.agents/hooks/**       **/.agents/agents/**    **/.agents/commands/**
    **/_RESEARCH/**           **/RESEARCH/**          **/LEARNING/**
    **/KNOWLEDGE-BASE/**
    **/.claude/tools/**       **/.claude/agents/**    **/.claude/commands/**
    **/specs/**               (seed copies of the files above)

UNGUARDED (identifiers belong here and are not the model's to strip):
    PROJECTS/**   tasks/**   DRAFTS/**   _PROJECTS/**   __archive/**   anything else

WHAT IS SURFACED (never blocked)
    a project alias, from the station term list (~/.claude/private/identifier-terms.txt,
      gitignored, one term per line) plus the PROJECTS/ folder names of the target's
      own repo where it has any. Whole word. A term written in mixed case matches
      exactly as typed, so "Widget" never fires on "widget"; a term written all upper
      or all lower matches any capitalization.
    a person's initials with a role code, `AB (ROLE1)` in shape
    an environment-prefixed catalog: an environment name joined to a medallion
      layer as one word
    a work-item id, `STORY-000001` in shape, whose digits are not a synthetic run.
      NNNNnn, repdigits, consecutive runs and zero-padded counters are fixtures and
      pass silently. Shape cannot tell a real tracker number from a made-up one, so
      the model judges.

    The examples above are deliberately synthetic. A detector's own documentation
    is the easiest place for a real value to hide, because nobody reads a rule
    table looking for the thing the rule describes.

Every pattern and the term-matching rule are the sanitize skill's (skills/sanitize/
scripts/detect.py, the one rule source), found beside this hook's folder
(SANITIZE_SCRIPTS overrides, for tests). This file holds only the path rule and the
report.

Only NEW content is checked (Write content, Edit/MultiEdit new_string, NotebookEdit
new_source). old_string is exempt: matching bytes already on disk requires reproducing
them, and this hook must never make an existing identifier unremovable.

Always exits 0. A finding is printed as a PreToolUse `additionalContext` payload,
which the model sees while the write proceeds. On any internal error the hook stays
silent apart from a stderr note, so it can never brick editing.
"""
import importlib.util
import json
import os
import pathlib
import re
import sys


def _load_detect():
    """The engine by exact file path: a missing folder must not import some other
    module that happens to be named `detect`."""
    base = pathlib.Path(os.environ.get("SANITIZE_SCRIPTS") or
                        pathlib.Path(__file__).resolve().parent.parent / "skills" / "sanitize" / "scripts")
    path = base / "detect.py"
    if not path.is_file():
        raise FileNotFoundError("detect.py")
    spec = importlib.util.spec_from_file_location("detect", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["detect"] = module
    spec.loader.exec_module(module)
    return module


try:
    detect = _load_detect()
except Exception:                                  # reported by main(); the hook stays silent
    detect = None

GUARDED = (
    ("/.claude/skills/",), ("/.agents/skills/",), ("/.claude/hooks/",),
    ("/.claude/tools/",), ("/.claude/agents/",), ("/.claude/commands/",),
    # This repo's own hooks, subagents and commands travel exactly as its skills do.
    ("/.agents/hooks/",), ("/.agents/agents/",), ("/.agents/commands/",),
    # Research folders under both names: this repo's _RESEARCH/ and a vault's RESEARCH/.
    ("/_RESEARCH/",), ("/RESEARCH/",), ("/LEARNING/",), ("/KNOWLEDGE-BASE/",),
    # A station spec carries the seed copies of the files above. The live hook
    # under ~/.claude/hooks/ was guarded and its published twin was not, so the
    # same bytes were checked in one location and unchecked in the other.
    ("/specs/",),
)
# Checked before GUARDED. A project workspace legitimately holds identifiers even when
# it sits under a guarded-looking path; the list is the one the review sweep uses.
EXEMPT = detect.PROJECT_PATHS if detect else ("/PROJECTS/", "/_PROJECTS/", "/tasks/", "/DRAFTS/", "/__archive/")

WORK_ITEM_WHY = "a work-item identifier that is not a synthetic run"
REASONS = {
    "role_code": "a person's initials with a role code",
    "catalog": "an environment-prefixed catalog name",
    "work_item": WORK_ITEM_WHY,
}
# Kept for the commit-message hook, which imports these names until it retires.
WORK_ITEM_RE = detect.WORK_ITEM if detect else re.compile(r"(?!)")
synthetic = detect.synthetic if detect else (lambda digits: True)

# Paths this hook always checks, whatever else is guarded: itself and the list.
SELF_GUARDED = ("/hooks/reject_identifiers.py", "/private/identifier-terms.txt")


def is_comment(line):
    """A comment is `#` followed by a space, or a bare `#`. `#tag` is a term."""
    s = line.strip()
    return s == "#" or s.startswith("# ")


def station_terms():
    return set(detect.station_terms_lenient() or ()) if detect else set()


def repo_of(path):
    for parent in [path] + list(path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def aliases_for(path):
    """The station term list, plus subjects derived from the target repo's own
    PROJECTS/ folders where it has any."""
    return station_terms() | detect.project_aliases(repo_of(path))


def guarded(path_str):
    normalized = path_str.replace(os.sep, "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    # The detector and its list are guarded first and unconditionally: a term written
    # into this file's comments, or into the list's header, is the same leak in the
    # one place a scrub never looks.
    if normalized.endswith(SELF_GUARDED):
        return True
    if any(marker in normalized for marker in EXEMPT):
        return False
    return any(marker in normalized for group in GUARDED for marker in group)


def self_text(target, text):
    """For a write to the term list, check only its comment lines; the entries ARE
    the terms. For any other target, check the text as given."""
    normalized = str(target).replace(os.sep, "/")
    if normalized.endswith(SELF_GUARDED[1]):
        return "\n".join(ln for ln in text.splitlines() if is_comment(ln))
    return text


def alias_hits(text, aliases):
    """(value, reason, start) for every term-list alias in text, by the shared term rule
    on the raw text (whole token, case kept for a mixed-case term, spacing as written)."""
    if not detect:
        return []
    out = []
    for alias in sorted(aliases):
        for match in detect.term_pattern(alias).finditer(text):
            out.append((match.group(0), "a project alias", match.start()))
    return out


def findings(text, aliases):
    """(matched value, reason, start) triples. Callers that talk to the model report the
    reason and the position, never the value: the list is not the model's to read."""
    hits = [(text[h.start:h.end], REASONS[h.cls], h.start)
            for h in detect.find(text) if h.cls in REASONS]
    hits.extend(alias_hits(text, aliases))
    return hits


def describe(hits, scanned):
    """Human-readable hit list that never carries a matched value: reason, line in
    the scanned text, and length. The model wrote the text, so that locates it."""
    seen, out = set(), []
    for value, why, pos in hits:
        if value in seen:
            continue
        seen.add(value)
        lineno = scanned.count("\n", 0, pos) + 1
        out.append(f"{why}, line {lineno}, {len(value)} chars")
    return out


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        ti = payload.get("tool_input", {}) or {}
        tool = payload.get("tool_name", "")
        if tool == "Write":
            text = ti.get("content", "")
        elif tool == "Edit":
            text = ti.get("new_string", "")
        elif tool == "NotebookEdit":
            text = ti.get("new_source", "")
        elif tool == "MultiEdit":
            edits = ti.get("edits", [])
            text = "\n".join(e.get("new_string", "") for e in edits
                             if isinstance(e, dict)) if isinstance(edits, list) else ""
        else:
            return 0
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if not isinstance(text, str) or not text or not target:
            return 0
        if not guarded(str(target)):
            return 0
        if detect is None:
            print("reject_identifiers: the sanitize detectors did not load; write allowed unchecked",
                  file=sys.stderr)
            return 0
        path = pathlib.Path(target).expanduser()
        scanned = self_text(target, text)
        hits = findings(scanned, aliases_for(path))
        if not hits:
            return 0
    except Exception as exc:                                  # never brick editing
        print(f"reject_identifiers hook error, write allowed: {exc}", file=sys.stderr)
        return 0

    # Report where and why, never what.
    detail = describe(hits, scanned)

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            "IDENTIFIER CHECK (write allowed) on a file that travels: "
            f"{target}. Hits: {'; '.join(detail[:8])}{' ...' if len(detail) > 8 else ''}. "
            "Judge each one: if it is a private project, client or person identifier, "
            "or a real tracker number, replace it now with a role description or a "
            "synthetic stand-in, or move the content under PROJECTS/ or tasks/. If it "
            "is an ordinary word or a fixture, leave it and say so in one line to the "
            "user. Do not quote the token back.")}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

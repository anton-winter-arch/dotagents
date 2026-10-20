#!/usr/bin/env python3
"""PreToolUse hook: reject invisible / non-standard characters in NEW content.

Checks only what the model is writing (Write content, Edit new_string,
MultiEdit edits[].new_string, NotebookEdit new_source). old_string is exempt
by design: matching existing file bytes requires reproducing whatever is
already there.

Allowed whitespace: space, tab, LF, CR. Everything else that renders as
nothing or as a look-alike space is rejected: NBSP, soft hyphen, zero-widths,
bidi controls, BOM, word joiners, line/paragraph separators, exotic Unicode
spaces, variation selectors, interlinear annotation marks, private use.

Exit 2 blocks the tool call and feeds stderr back to the model.

The codepoint table is the sanitize skill's (skills/sanitize/scripts/detect.py, the one
rule source), found beside this hook's folder (SANITIZE_SCRIPTS overrides, for tests).
This hook blocks every row of it, a BOM at offset 0 included. When the table cannot
load, the write proceeds and the model is told the check did not run.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path


def load_detect():
    """The engine by exact file path: a missing folder must not import some other
    module that happens to be named `detect`."""
    base = Path(os.environ.get("SANITIZE_SCRIPTS") or
                Path(__file__).resolve().parent.parent / "skills" / "sanitize" / "scripts")
    path = base / "detect.py"
    if not path.is_file():
        raise FileNotFoundError("detect.py")
    spec = importlib.util.spec_from_file_location("detect", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["detect"] = module
    spec.loader.exec_module(module)
    return module


def bad_chars(text, detect):
    hits = {}
    for i, _rule in detect.hidden_chars(text, skip_leading_bom=False):
        hits.setdefault(f'U+{ord(text[i]):04X}', []).append(i)
    return hits


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get('tool_input', {}) or {}
    tool = payload.get('tool_name', '')
    if tool == 'Write':
        text = ti.get('content', '')
    elif tool == 'Edit':
        text = ti.get('new_string', '')
    elif tool == 'NotebookEdit':
        text = ti.get('new_source', '')
    elif tool == 'MultiEdit':
        edits = ti.get('edits', [])
        text = '\n'.join(e.get('new_string', '') for e in edits
                         if isinstance(e, dict)) if isinstance(edits, list) else ''
    else:
        return 0
    if not isinstance(text, str):
        return 0
    try:
        detect = load_detect()
    except Exception as exc:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": f"reject_invisibles: the shared codepoint table did not load "
                                 f"({type(exc).__name__}), so hidden characters in this write were not checked."}}))
        return 0
    hits = bad_chars(text, detect)
    if not hits:
        return 0
    detail = '; '.join(
        f'{cp} at offset(s) {", ".join(map(str, pos[:5]))}'
        f'{" ..." if len(pos) > 5 else ""}'
        for cp, pos in sorted(hits.items()))
    print(f'invisible/non-standard characters rejected in new content: '
          f'{detail}. Replace each with a plain space or remove it; '
          f'old_string matching is exempt, new content is not.',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())

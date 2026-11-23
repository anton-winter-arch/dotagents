#!/usr/bin/env python3
"""Check a seat's delivery against its board: structure only, never substance.

READ. Given the delivered head and the board commit, it reads the board as it is at
the board commit through sprint-board's board_query.py, finds the story's latest
evidence entry for the head, and checks:

- the head is an ancestor of the board commit, and every commit between them
  touches only the board file;
- the story's criteria, VALIDATION and Definition of Done text equals the text at
  the assignment commit, so the lines the user agreed to are the lines checked;
- every criterion, VALIDATION and Definition of Done line has exactly one evidence
  item, and every item parses and is in range;
- the evidence base is an ancestor of the head, and the security token is not blocked;
- every state move since the last verdict is an allowed move, and the State line
  equals the last state line in COMMENTS.

It runs none of the story's commands; its only subprocesses are git and board_query.py.
The grammar it reads is references/protocol.md.

    packet_check.py --repo <path> --board <repo-relative path> --story <ID> \\
                    --head <sha> --board-at <sha> --assigned-at <sha> \\
                    [--feature-review] [--json]

Exit 0 complete; 1 incomplete, naming each problem; 2 usage or git error.
"""
import argparse
import json
import os
import posixpath
import re
import sys
import tempfile
from pathlib import Path

import procguard

HERE = Path(__file__).resolve().parent
BOARD_QUERY = HERE.parent.parent / "sprint-board" / "scripts" / "board_query.py"
LIMIT = 60  # seconds per subprocess

SHA = r"[0-9a-f]{7,40}"
STATE_RE = re.compile(r"^- (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (.+?) -> (.+?) by (.+)$")
HEADER_RE = re.compile(r"^- (evidence|verdict)\b")
EVIDENCE_RE = re.compile(rf"^- evidence ({SHA}) base ({SHA}) security (safe|pending|blocked)$")
VERDICT_RE = re.compile(rf"^- verdict ({SHA}) (accept|reject)$")
EVIDENCE_ITEM_RE = re.compile(r"^  - (criteria|validation|dod):(\d+) (pass|manual|exception) (\S.*)$")
VERDICT_ITEM_RE = re.compile(r"^  - (criteria|validation|dod|security):(\d+) (pass|fail|pending) (\S.*)$")

# board_query.py --story --json list for each evidence list name.
LISTS = {"criteria": "criteria", "validation": "validation", "dod": "definition_of_done"}

ALLOWED = {("(none)", "New"), ("New", "Active"), ("Active", "Blocked"), ("Blocked", "Active"),
           ("Active", "Resolved"), ("Resolved", "Active"), ("Resolved", "Closed"),
           ("Closed", "Active")}


class GitError(Exception):
    pass


def problem(line, code, message):
    return {"line": line, "code": code, "message": message}


# ---- subprocesses -----------------------------------------------------------------

def git(repo, *args, ok=(0,)):
    # The repo is the seat's; its config must not get a command run from here.
    proc = procguard.run(["git", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
                         capture_output=True, text=True, timeout=LIMIT)
    if proc.returncode not in ok:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.returncode}")
    return proc


def resolve(repo, rev):
    """Full sha of a commit, or None when rev names no commit."""
    proc = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", ok=(0, 1))
    return proc.stdout.strip() if proc.returncode == 0 else None


def is_ancestor(repo, a, b):
    return git(repo, "merge-base", "--is-ancestor", a, b, ok=(0, 1)).returncode == 0


def touched(repo, head, board_at):
    """(sha, path) for every path changed by a commit in head..board_at, merges included.
    -z keeps unusual paths unquoted; each commit's sha token is marked with \\x01."""
    out = git(repo, "log", "-z", "--format=%x01%H", "-m", "--name-only", "--no-renames",
              "--no-ext-diff", "--no-textconv", f"{head}..{board_at}").stdout
    sha = None
    for token in out.split("\0"):
        token = token.lstrip("\n")
        if token.startswith("\x01"):
            sha = token[1:]
        elif token:
            yield sha, token


def story_at(repo, board_path, board_at, story):
    """board_query.py --story --json on the board as it is at board_at; None if unknown."""
    # cat-file blob prints the stored bytes; no textconv or filter can apply.
    text = git(repo, "cat-file", "blob", f"{board_at}:{board_path}").stdout
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "board.md"
        copy.write_text(text, encoding="utf-8")
        proc = procguard.run([sys.executable, str(BOARD_QUERY), str(copy), "--story", story,
                              "--json"], capture_output=True, text=True, timeout=LIMIT)
    if proc.returncode == 1 and not proc.stdout:
        return None
    if proc.returncode != 0:
        raise GitError(f"board_query.py: {proc.stderr.strip() or proc.returncode}")
    return json.loads(proc.stdout)


# ---- COMMENTS -----------------------------------------------------------------------

def parse_comments(comments, sizes):
    """Events in COMMENTS order, plus problems found while parsing.

    An event is a dict with kind "state", "evidence" or "verdict". Entry items are
    checked for syntax, range and duplicates here; coverage is checked by the caller,
    for the one evidence entry that counts."""
    events, problems, entry = [], [], None
    for c in comments:
        line, text = c["line"], c["text"].rstrip()
        if not text.startswith(" "):
            entry = None
            m = STATE_RE.match(text)
            if m:
                events.append({"kind": "state", "line": line, "old": m.group(2), "new": m.group(3)})
                continue
            h = HEADER_RE.match(text)
            if not h:
                continue  # free text
            kind = h.group(1)
            m = (EVIDENCE_RE if kind == "evidence" else VERDICT_RE).match(text)
            if not m:
                problems.append(problem(line, "bad-header", f"unparseable {kind} header: {text}"))
                continue
            entry = {"kind": kind, "line": line, "head": m.group(1), "items": {}}
            if kind == "evidence":
                entry.update(base=m.group(2), security=m.group(3))
            else:
                entry["result"] = m.group(2)
            events.append(entry)
            continue
        if entry is None:
            continue  # indented free text, or an item under a broken header
        m = (EVIDENCE_ITEM_RE if entry["kind"] == "evidence" else VERDICT_ITEM_RE).match(text)
        if not m:
            problems.append(problem(line, "bad-item", f"unparseable {entry['kind']} item: {text.strip()}"))
            continue
        name, n = m.group(1), int(m.group(2))
        limit = 1 if name == "security" else sizes[name]
        key = f"{name}:{n}"
        if not 1 <= n <= limit:
            problems.append(problem(line, "out-of-range", f"{key} is out of range; the story has "
                                    f"{limit} {name} line(s)"))
        elif key in entry["items"]:
            problems.append(problem(line, "duplicate-item", f"{key} appears twice in one entry"))
        else:
            entry["items"][key] = line
    return events, problems


def check_trail(events, story, same):
    """Moves since the last verdict, and the State line against the last state line."""
    problems = []
    verdicts = [i for i, ev in enumerate(events) if ev["kind"] == "verdict"]
    start = verdicts[-1] if verdicts else -1
    current = "(none)"
    last_evidence = last_verdict = None
    for i, ev in enumerate(events):
        if ev["kind"] == "evidence":
            last_evidence = ev
        elif ev["kind"] == "verdict":
            last_verdict = ev
        if ev["kind"] != "state":
            continue
        old, new, prev = ev["old"], ev["new"], current
        current = new
        if i < start:
            continue  # history before the last verdict was checked when that verdict was given
        if prev != old:
            problems.append(problem(ev["line"], "broken-trail",
                                    f"the move starts from {old}, but the state was {prev}"))
        elif (old, new) not in ALLOWED:
            problems.append(problem(ev["line"], "bad-move", f"{old} -> {new} is not an allowed move"))
        elif (old, new) == ("Resolved", "Closed") and not (
                last_verdict and last_evidence and last_verdict["result"] == "accept"
                and same(last_verdict["head"], last_evidence["head"])):
            problems.append(problem(ev["line"], "bad-move", "Resolved -> Closed needs an accept "
                                    "verdict for the head of the latest evidence entry"))
    stamps = [ev for ev in events if ev["kind"] == "state"]
    if stamps and stamps[-1]["new"] != story["state"]:
        problems.append(problem(story["line"], "state-mismatch",
                                f"State is {story['state']}, but the last state line says "
                                f"{stamps[-1]['new']}"))
    if not stamps and story["state"]:
        problems.append(problem(story["line"], "state-unstamped",
                                f"State is {story['state']}, but COMMENTS has no state line"))
    return problems


# ---- the check ------------------------------------------------------------------------

def check(repo, board, story_id, head, board_at, assigned_at, feature_review=False):
    """Every problem with the delivery, in board order within each check; [] when complete.
    feature_review skips the board-only check on head..board_at: by then later stories'
    code legitimately follows a Closed story's head.
    Raises GitError when a commit does not resolve or git fails."""
    head_sha, at_sha, assigned_sha = (resolve(repo, r) for r in (head, board_at, assigned_at))
    for rev, sha in ((head, head_sha), (board_at, at_sha), (assigned_at, assigned_sha)):
        if sha is None:
            raise GitError(f"{rev} is not a commit in {repo}")
    prefix = git(repo, "rev-parse", "--show-prefix").stdout.strip()
    board_path = posixpath.normpath(posixpath.join(prefix, board))

    problems = []
    if not is_ancestor(repo, head_sha, at_sha):
        problems.append(problem(None, "head-not-ancestor",
                                f"the head {head} is not an ancestor of the board commit {board_at}"))
    elif not feature_review:
        for sha, path in touched(repo, head_sha, at_sha):
            if path != board_path:
                problems.append(problem(None, "non-board-commit",
                                        f"{sha[:12]} after the head changes {path}"))

    story = story_at(repo, board_path, at_sha, story_id)
    if story is None:
        return problems + [problem(None, "unknown-story", f"{story_id} is not one story on {board}")]

    # The criteria the user agreed to are the ones at assignment; a change since voids
    # the delivery, and the lead runs VALIDATION lines from the assignment commit.
    agreed = story_at(repo, board_path, assigned_sha, story_id)
    if agreed is None:
        problems.append(problem(story["line"], "criteria-changed",
                                f"{story_id} is not on the board at the assignment commit "
                                f"{assigned_at}"))
    for key in LISTS.values() if agreed else ():
        if [c["text"] for c in agreed[key]] != [c["text"] for c in story[key]]:
            line = story[key][0]["line"] if story[key] else story["line"]
            problems.append(problem(line, "criteria-changed",
                                    f"{key} differs from the board at the assignment commit "
                                    f"{assigned_at}"))

    cache = {}

    def full(rev):
        if rev not in cache:
            cache[rev] = resolve(repo, rev)
        return cache[rev]

    def same(a, b):
        return full(a) is not None and full(a) == full(b)

    sizes = {name: len(story[key]) for name, key in LISTS.items()}
    events, found = parse_comments(story["comments"], sizes)
    problems += found

    entries = [ev for ev in events if ev["kind"] == "evidence" and full(ev["head"]) == head_sha]
    if not entries:
        problems.append(problem(None, "no-evidence", f"{story_id} has no evidence entry for {head}"))
    else:
        entry = entries[-1]
        for name, key in LISTS.items():
            for n, item in enumerate(story[key], 1):
                if f"{name}:{n}" not in entry["items"]:
                    problems.append(problem(item["line"], "missing-item",
                                            f"no evidence for {name}:{n} ({item['text']})"))
        base = full(entry["base"])
        if base is None or not is_ancestor(repo, base, head_sha):
            problems.append(problem(entry["line"], "base-not-ancestor",
                                    f"the base {entry['base']} is not an ancestor of the head"))
        if entry["security"] == "blocked":
            problems.append(problem(entry["line"], "security-blocked",
                                    "the security review blocked this delivery"))

    return problems + check_trail(events, story, same)


def sha_arg(value):
    if not re.fullmatch(SHA, value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a commit sha (7 to 40 lowercase hex)")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True, help="the seat's repo")
    ap.add_argument("--board", required=True, help="the board, relative to the repo")
    ap.add_argument("--story", required=True, help="STORY-<id>")
    ap.add_argument("--head", required=True, type=sha_arg, help="the delivered commit")
    ap.add_argument("--board-at", required=True, type=sha_arg,
                    help="the commit whose board is read")
    ap.add_argument("--assigned-at", required=True, type=sha_arg,
                    help="the seat's commit when the story was assigned")
    ap.add_argument("--feature-review", action="store_true",
                    help="skip the board-only check after the head; later stories' code follows")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    procguard.install_signal_handlers()
    try:
        problems = check(Path(args.repo), args.board, args.story, args.head, args.board_at,
                         args.assigned_at, args.feature_review)
    except (GitError, ValueError, procguard.subprocess.TimeoutExpired, OSError) as e:
        # ValueError covers undecodable board text and unparseable board_query output,
        # which must not pass for an ordinary "incomplete" (exit 1).
        print(f"packet_check: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"complete": not problems, "problems": problems}, indent=2))
    elif not problems:
        print(f"{args.story}: complete")
    else:
        for p in problems:
            print(f"{p['line'] if p['line'] is not None else '-'}: {p['code']}: {p['message']}")
        print(f"{args.story}: incomplete, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

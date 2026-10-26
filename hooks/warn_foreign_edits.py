#!/usr/bin/env python3
"""Warn a session, before it writes, that something other than itself changed a git working tree it is working in.

Advisory only, never a permission decision. Design and rationale: tasks/SPEC-FOREIGN-EDIT-WARNING.md.

Attribution is by timing. Every tool call is bracketed by the session's own PreToolUse and PostToolUse
(or PostToolUseFailure), paired by tool_use_id, and every batch ends with PostToolBatch, denied calls
included. After the session's calls settle, the hook records each touched repo's state: HEAD, branch,
and every path `git status` reports with its status code, mtime and size. At the session's next write
or shell call it compares: a change in between is foreign. While any of the session's calls is in
flight the comparison waits. A batch of file-write calls subtracts its own paths and reports the
rest; a parallel batch that held a shell call is ambiguous and only logged; a single shell call's
changes are the session's own. Subagent calls share the session id, so they count as the session's.

Signals: live (a foreign change or a HEAD move between the session's calls, worded by age against
FOREIGN_EDIT_WINDOW_S, default 300), held (uncommitted work at the session's first look at a repo,
reported once), background (a foreign change while a background command this session launched in the
last 15 minutes may still be running), ambiguous (logged only).

FOREIGN_EDIT_MODE: record (default) logs to ~/.local/state/foreign-edit/log.jsonl and says nothing;
warn also tells the model (additionalContext) and the user (systemMessage); off does nothing. The log
holds paths, ages and counts, never file content.

Known gaps: an outside edit that lands during one of the session's own single calls is counted as the
session's; a PostToolUse hook that rewrites files can run after the snapshot; a folder set through a
variable or `bash -c` is not followed. Exit 0 on every path, silent on any internal error. A git call
that times out abandons the event and starts a back-off (FOREIGN_EDIT_BACKOFF_S, default 600) in which
the session is not scanned, so a slow repo costs one timeout, and the back-off ends with a silent new
baseline. A repo whose own config sets a filter command (filter.*.clean or .process at local or
worktree scope) is never scanned, because `git status` would run that command; the check runs at the
session's first look at a repo, so a filter added to a watched repo's config later in the session is
not seen, and submodules are not entered at all.
"""
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_input = _load("_input")
_shell_dirs = _load("_shell_dirs")


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


MODE = os.environ.get("FOREIGN_EDIT_MODE", "record")
STATE_DIR = Path(os.environ.get("FOREIGN_EDIT_STATE_DIR") or Path.home() / ".local" / "state" / "foreign-edit")
WINDOW_S = _num("FOREIGN_EDIT_WINDOW_S", 300)
REREPORT_S = _num("FOREIGN_EDIT_REREPORT_S", 600)
INFLIGHT_TTL_S = _num("FOREIGN_EDIT_INFLIGHT_TTL_S", 900)
GIT_TIMEOUT_S = _num("FOREIGN_EDIT_GIT_TIMEOUT_S", 2)
BACKOFF_S = _num("FOREIGN_EDIT_BACKOFF_S", 600)
# A repo's own config can name a command git runs while it reads the tree; such a repo is never scanned.
RISKY_CONFIG = r"^filter\..*\.(clean|process)$"
BACKGROUND_S = 900
STALE_SESSION_S = 7 * 86400
MAX_REPOS = 5
MAX_DIR_LOOKUPS = 4
MAX_SHOWN = 2
WATCHED = {"file-write", "shell"}


class GitTimeout(Exception):
    pass


def run_git(args: list[str], where: str) -> bytes | None:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", where, *args],
                           capture_output=True, timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise GitTimeout from exc
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def repo_for(path: str) -> tuple[str, str] | None:
    """(top level, git dir) of the repo holding `path`, from its nearest existing folder."""
    p = Path(path)
    if not p.is_dir():
        p = p.parent
    while not p.exists() and p != p.parent:
        p = p.parent
    out = run_git(["rev-parse", "--show-toplevel", "--absolute-git-dir"], str(p))
    lines = out.decode("utf-8", "surrogateescape").splitlines() if out else []
    if len(lines) < 2:
        return None
    return os.path.realpath(lines[0]), os.path.realpath(lines[1])


def parse_status(raw: bytes) -> tuple[str | None, str | None, dict[str, str]]:
    """HEAD commit, branch and {path: status code} from `status --porcelain=v2 -z --branch`."""
    head = ref = None
    paths: dict[str, str] = {}
    records = raw.decode("utf-8", "surrogateescape").split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if rec.startswith("# branch.oid "):
            value = rec[len("# branch.oid "):]
            head = None if value == "(initial)" else value
        elif rec.startswith("# branch.head "):
            value = rec[len("# branch.head "):]
            ref = None if value == "(detached)" else value
        elif rec.startswith("1 "):
            parts = rec.split(" ", 8)
            if len(parts) == 9:
                paths[parts[8]] = parts[1]
        elif rec.startswith("2 "):
            parts = rec.split(" ", 9)
            if len(parts) == 10:
                paths[parts[9]] = parts[1]
            i += 1  # the original path of a rename or copy
        elif rec.startswith("u "):
            parts = rec.split(" ", 10)
            if len(parts) == 11:
                paths[parts[10]] = parts[1]
        elif rec.startswith("? "):
            paths[rec[2:]] = "??"
    return head, ref, paths


def snapshot(top: str) -> dict | None:
    # Submodules are not entered: their own config could hold a filter command the top repo's check never saw.
    raw = run_git(["status", "--porcelain=v2", "-z", "--untracked-files=all", "--branch", "--ignore-submodules=all"], top)
    if raw is None:
        return None
    head, ref, paths = parse_status(raw)
    files = {}
    for path, code in paths.items():
        try:
            st = os.lstat(os.path.join(top, path))
            files[path] = [code, st.st_mtime, st.st_size]
        except OSError:
            files[path] = [code, None, None]
    return {"head": head, "ref": ref, "files": files}


def diff(old: dict, new: dict) -> tuple[list[dict], dict | None]:
    """Changed paths and a HEAD or branch move between two snapshots."""
    changes = []
    for path, entry in new["files"].items():
        before = old["files"].get(path)
        if before != entry:
            changes.append({"path": path, "mtime": entry[1], "kind": "added" if before is None else "changed"})
    for path in old["files"]:
        if path not in new["files"]:
            changes.append({"path": path, "mtime": None, "kind": "cleaned"})
    head = None
    if (old["head"], old["ref"]) != (new["head"], new["ref"]):
        head = {"from": old["head"], "to": new["head"], "ref_from": old["ref"], "ref_to": new["ref"]}
    return changes, head


# --- state ----------------------------------------------------------------------------------------

def _empty_state() -> dict:
    return {"repos": {}, "inflight": {}, "batch": {"active": False, "paths": [], "shell": False, "calls": 0},
            "background": [], "pending": []}


class SessionState:
    """One JSON file per session, read and written under an exclusive lock, swapped in atomically."""

    def __init__(self, session_id: str):
        folder = STATE_DIR / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(STATE_DIR, 0o700)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
        self.path = folder / f"{name}.json"
        self.lock = open(folder / f"{name}.lock", "a")
        deadline = time.time() + 5
        while True:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    raise
                time.sleep(0.02)
        try:
            self.data = json.loads(self.path.read_text()) if self.path.exists() else _empty_state()
        except ValueError:
            self.data = _empty_state()

    def save(self) -> None:
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.data))
        os.replace(tmp, self.path)

    def close(self) -> None:
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


def log(entry: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(STATE_DIR / "log.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# --- detection ------------------------------------------------------------------------------------

def known_repos(state: dict) -> list[str]:
    """The most recently touched repos that are safe to scan."""
    repos = {g: r for g, r in state["repos"].items() if not r.get("unsafe")}
    return sorted(repos, key=lambda g: repos[g].get("touched", 0), reverse=True)[:MAX_REPOS]


def rebaseline(state: dict) -> None:
    """After a back-off the bookkeeping has gaps: start over from the tree as it is, reporting nothing."""
    state["inflight"] = {}
    state["batch"] = {"active": False, "paths": [], "shell": False, "calls": 0}
    for gitdir in known_repos(state):
        snap = snapshot(state["repos"][gitdir]["top"])
        if snap is not None:
            state["repos"][gitdir]["baseline"] = snap
    state.pop("backoff_since", None)


def risky_config(top: str) -> bool:
    """A filter command set in the repo's own config runs during `git status`; reading config runs nothing."""
    out = run_git(["config", "--show-scope", "--get-regexp", RISKY_CONFIG], top)
    scopes = [line.split("\t", 1)[0].split(" ", 1)[0] for line in (out or b"").decode("utf-8", "replace").splitlines()]
    return any(s in ("local", "worktree") for s in scopes)


def first_look(state: dict, top: str, gitdir: str, now: float) -> dict | None:
    if risky_config(top):
        state["repos"][gitdir] = {"top": top, "unsafe": True, "touched": now}
        return {"signal": "unsafe-config", "repo": top, "changes": [], "head": None, "committed": [], "silent": True}
    snap = snapshot(top)
    if snap is None:
        return None
    state["repos"][gitdir] = {"top": top, "baseline": snap, "touched": now, "last_report": 0,
                              "reported": {p: e[1] if e[1] is not None else "cleaned" for p, e in snap["files"].items()}}
    if not snap["files"]:
        return None
    changes = [{"path": p, "mtime": e[1], "kind": "held"} for p, e in snap["files"].items()]
    return {"signal": "held", "repo": top, "changes": changes, "head": None, "committed": []}


def reportable(repo: dict, changes: list[dict], head: dict | None, signal: str, now: float) -> dict | None:
    """Apply once-per-set and the re-save cap; record what gets reported."""
    picked = []
    reported = repo["reported"]
    for c in changes:
        mark = c["mtime"] if c["mtime"] is not None else "cleaned"
        prev = reported.get(c["path"])
        newer = isinstance(prev, (int, float)) and isinstance(mark, (int, float)) and mark > prev
        if prev is None or (prev != mark and (not isinstance(mark, (int, float)) or not isinstance(prev, (int, float)) or newer)
                            and now - repo["last_report"] >= REREPORT_S):
            picked.append(c)
            reported[c["path"]] = mark
    if not picked and not head:
        return None
    committed = []
    if head and head["from"] and head["to"]:
        out = run_git(["diff", "--name-only", head["from"], head["to"]], repo["top"])
        committed = out.decode("utf-8", "surrogateescape").splitlines() if out else []
    repo["last_report"] = now
    return {"signal": signal, "repo": repo["top"], "changes": picked, "head": head, "committed": committed}


def background_active(state: dict, now: float) -> bool:
    state["background"] = [t for t in state["background"] if now - t < BACKGROUND_S]
    return bool(state["background"])


def record(det: dict, session: str, inflight: int, now: float) -> None:
    log({"time": round(now, 3), "session": session, "repo": det["repo"], "signal": det["signal"],
         "paths": [c["path"] for c in det["changes"]],
         "ages_s": [round(now - c["mtime"], 1) if c["mtime"] is not None else None for c in det["changes"]],
         "head": bool(det["head"]), "committed": len(det["committed"]), "inflight": inflight})


def compare(state: dict, gitdir: str, now: float) -> dict | None:
    repo = state["repos"][gitdir]
    snap = snapshot(repo["top"])
    if snap is None:
        return None
    changes, head = diff(repo["baseline"], snap)
    repo["baseline"] = snap
    if not changes and not head:
        return None
    signal = "background" if background_active(state, now) else "live"
    return reportable(repo, changes, head, signal, now)


def settle(state: dict, session: str, now: float) -> None:
    """The session's calls have all ended: attribute what changed during them and take a new baseline."""
    batch = state["batch"]
    if not batch["active"]:
        return
    own = set(batch["paths"])
    for gitdir in known_repos(state):
        repo = state["repos"][gitdir]
        snap = snapshot(repo["top"])
        if snap is None:
            continue
        changes, head = diff(repo["baseline"], snap)
        repo["baseline"] = snap
        residue = [c for c in changes if os.path.realpath(os.path.join(repo["top"], c["path"])) not in own]
        if not residue and not head:
            continue
        if batch["shell"]:
            if batch["calls"] > 1:
                record({"signal": "ambiguous", "repo": repo["top"], "changes": residue, "head": head,
                        "committed": []}, session, 0, now)
            continue
        det = reportable(repo, residue, head, "live", now)
        if det:
            record(det, session, 0, now)
            det["logged"] = True
            state["pending"].append(det)
    state["batch"] = {"active": False, "paths": [], "shell": False, "calls": 0}


def drop_inflight(state: dict, keep) -> bool:
    before = len(state["inflight"])
    state["inflight"] = {k: v for k, v in state["inflight"].items() if keep(v)}
    return len(state["inflight"]) < before


def touched(ev) -> list[tuple[str, str]]:
    places = []
    if ev.tool_class == "file-write":
        places = list(ev.paths)
    elif ev.tool_class == "shell":
        places = [ev.cwd] if ev.cwd else []
        for words, here in _shell_dirs.walk(ev.command, ev.cwd):
            places.append(here)
            if Path(words[0]).name == "git":
                places.append(_shell_dirs.git_target(words, here)[0])
    seen, out = set(), []
    for place in dict.fromkeys(os.path.normpath(p) for p in places if p):
        if len(seen) >= MAX_DIR_LOOKUPS:
            break
        found = repo_for(place)
        if found and found[1] not in seen:
            seen.add(found[1])
            out.append(found)
    return out


# --- wording --------------------------------------------------------------------------------------

def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600)} h"


def _shown(text: str, cap: int = 32) -> str:
    """Printable characters only, and a long path keeps its tail, where the file name is."""
    clean = "".join(ch for ch in text if ch.isprintable())
    return clean if len(clean) <= cap else "..." + clean[-(cap - 3):]


def _names(paths: list[str]) -> str:
    out = ", ".join(_shown(p) for p in paths[:MAX_SHOWN])
    return out + (f" +{len(paths) - MAX_SHOWN} more" if len(paths) > MAX_SHOWN else "")


def describe(det: dict, now: float) -> str:
    """One line, kept short: it lands in the model's context on every report."""
    changes = det["changes"]
    ages = [now - c["mtime"] for c in changes if c["mtime"] is not None]
    home = str(Path.home())
    repo = _shown("~" + det["repo"][len(home):] if det["repo"].startswith(home + os.sep) else det["repo"])
    names = _names([c["path"] for c in changes])
    if det["signal"] == "held":
        newest = f" (newest {_age(min(ages))})" if ages else ""
        return f"Uncommitted work in {repo}, not made by this session: {names}{newest}. Ask before touching it."
    parts = []
    if changes:
        when = f"{_age(min(ages))} ago" if ages else "just now"
        if ages and min(ages) > WINDOW_S:
            when = f"while this session was idle, {when}"
        parts.append(f"{names} ({when})")
    if det["head"]:
        h = det["head"]
        move = f"HEAD moved {(h['from'] or 'none')[:7]}->{(h['to'] or 'none')[:7]}"
        n = len(det["committed"])
        if n:
            move += f", committing {_shown(det['committed'][0])}" if n == 1 else f", {n} files committed"
        parts.append(move)
    text = f"Foreign edits in {repo}, not by this session: " + "; ".join(parts) + ". Check before writing."
    if det["signal"] == "background":
        text += " (Maybe this session's background command.)"
    return text


def speak(event: str, dets: list[dict], now: float) -> None:
    dets = [d for d in dets if not d.get("silent")]
    if MODE != "warn" or not dets:
        return
    text = "\n".join(describe(d, now) for d in dets[:3])
    print(json.dumps({"systemMessage": text, "hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


# --- events ---------------------------------------------------------------------------------------

def prune_old_sessions(now: float) -> None:
    """A session is stale when its state file is; its lock goes with it, and a live session's lock stays."""
    folder = STATE_DIR / "sessions"
    for f in folder.glob("*.json"):
        try:
            if now - f.stat().st_mtime > STALE_SESSION_S:
                f.unlink()
                f.with_suffix(".lock").unlink(missing_ok=True)
        except OSError:
            pass


def backing_off(session_id: str, now: float) -> tuple[bool, bool]:
    """(in back-off, back-off just ended) from a read of the state file without the lock."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    try:
        since = json.loads((STATE_DIR / "sessions" / f"{name}.json").read_text()).get("backoff_since")
    except (OSError, ValueError, AttributeError):
        return False, False
    if since is None:
        return False, False
    return now - since < BACKOFF_S, now - since >= BACKOFF_S


def start_backoff(session_id: str, now: float) -> None:
    """A git call timed out: stop scanning for BACKOFF_S, so a slow repo costs one timeout, not one per call."""
    st = SessionState(session_id)
    try:
        st.data["backoff_since"] = now
        st.save()
    finally:
        st.close()
    log({"time": round(now, 3), "session": session_id, "repo": "", "signal": "timeout", "paths": [], "ages_s": [],
         "head": False, "committed": 0, "inflight": 0})


def main() -> int:
    if MODE == "off":
        return 0
    ev = _input.read_event()
    sid = ev.session_id
    if not sid or not ev.event:
        return 0
    raw = ev.raw
    agent = str(raw.get("agent_id") or "")
    now = time.time()
    e = ev.event
    if e in ("PreToolUse", "PostToolUse", "PostToolUseFailure") and ev.tool_class not in WATCHED:
        return 0
    if e not in ("SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
                 "SubagentStop", "UserPromptSubmit", "Stop"):
        return 0
    in_backoff, backoff_ended = backing_off(sid, now)
    if in_backoff:
        return 0
    try:
        return handle(ev, e, sid, agent, raw, now, backoff_ended)
    except GitTimeout:
        start_backoff(sid, now)
        return 0


def handle(ev, e: str, sid: str, agent: str, raw: dict, now: float, backoff_ended: bool) -> int:
    places = []
    if e == "SessionStart":
        home = os.environ.get("CLAUDE_PROJECT_DIR") or ev.cwd
        found = repo_for(home) if home else None
        places = [found] if found else []
        if not places:
            return 0
    elif e == "PreToolUse":
        places = touched(ev)

    st = SessionState(sid)
    try:
        state = st.data
        dets: list[dict] = []
        rebased = backoff_ended and "backoff_since" in state
        if rebased:
            rebaseline(state)
        if e == "SessionStart":
            prune_old_sessions(now)
            top, gitdir = places[0]
            if gitdir not in state["repos"]:
                det = first_look(state, top, gitdir, now)
                if det:
                    dets.append(det)
        elif e == "PreToolUse":
            if drop_inflight(state, lambda v: now - v["ts"] < INFLIGHT_TTL_S) and not state["inflight"]:
                state["batch"] = {"active": False, "paths": [], "shell": False, "calls": 0}
            dets.extend(state["pending"])
            state["pending"] = []
            idle = not state["inflight"] and not rebased
            for top, gitdir in places:
                if gitdir not in state["repos"]:
                    det = first_look(state, top, gitdir, now)
                    if det:
                        dets.append(det)
                state["repos"][gitdir]["touched"] = now
            if idle:
                for gitdir in known_repos(state):
                    det = compare(state, gitdir, now)
                    if det:
                        dets.append(det)
            tid = str(raw.get("tool_use_id") or f"anon-{now}")
            state["inflight"][tid] = {"agent": agent, "ts": now, "class": ev.tool_class}
            batch = state["batch"]
            batch["active"] = True
            batch["calls"] += 1
            if ev.tool_class == "file-write":
                batch["paths"].extend(os.path.realpath(p) for p in ev.paths)
            else:
                batch["shell"] = True
                ti = raw.get("tool_input") if isinstance(raw.get("tool_input"), dict) else {}
                if ti.get("run_in_background"):
                    state["background"].append(now)
            for det in dets:
                if not det.get("logged"):
                    record(det, sid, len(state["inflight"]) - 1, now)
        elif e in ("PostToolUse", "PostToolUseFailure"):
            tid = str(raw.get("tool_use_id") or "")
            if state["inflight"].pop(tid, None) is not None and not state["inflight"]:
                settle(state, sid, now)
        elif e == "PostToolBatch":
            drop_inflight(state, lambda v: v["agent"] != agent)
            if not state["inflight"]:
                settle(state, sid, now)
        elif e == "SubagentStop":
            if drop_inflight(state, lambda v: v["agent"] != agent) and not state["inflight"]:
                settle(state, sid, now)
        elif e in ("UserPromptSubmit", "Stop"):
            if drop_inflight(state, lambda v: v["agent"] != "") and not state["inflight"]:
                settle(state, sid, now)
        if e == "SessionStart":
            for det in dets:
                record(det, sid, 0, now)
        st.save()
    finally:
        st.close()
    if e in ("SessionStart", "PreToolUse"):
        speak(e, dets, now)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)

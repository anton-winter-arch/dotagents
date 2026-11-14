#!/usr/bin/env python3
"""Session web state shared by web_fetch_guard.py, download_guard.py, web_session_end.py
and web_download.py. Not a hook itself: it is copied beside them and loaded by path.

One small JSON file per session records, per host, whether the host refused a request,
when the next request to it may go out, and how many went out. A refusal (401, 403, 429
or 503) is final for the session: nothing here ever clears it. Requests to one host are
spaced MIN_DELAY seconds apart and capped at HOST_CAP per session.

The file lives in `<system temp>/web-guard-<uid>/<session id>/state.json`, so a session's
subagents share one state, two sessions share nothing, and nothing is written under a
repository or the home folder. web_session_end.py removes the folder; a session that ends
without that event leaves a few kilobytes for the operating system to clear.

Every change is made under an exclusive lock on a sibling lock file and written by
write-then-rename, so parallel subagents cannot corrupt the file. Stdlib only, Python 3.9.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

REFUSAL_CODES = (401, 403, 429, 503)
MIN_DELAY = 2.0          # seconds between requests to one host
HOST_CAP = 20            # requests to one host per session
REMIND_EVERY = 30 * 60   # seconds between download reminders in one session
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
# Government and military hosts: .gov and .mil, and their country forms such as gov.uk.
STRICT = re.compile(r"(^|\.)(gov|mil)(\.[a-z]{2})?$")
LOCAL = re.compile(r"^(localhost|127(\.[0-9]{1,3}){3}|::1|0\.0\.0\.0)$")


def number(name: str, default: float) -> float:
    """A tuning value from the environment; the tests shorten the delay through it."""
    try:
        return float(os.environ.get(name, ""))
    except ValueError:
        return default


def min_delay() -> float:
    return number("WEB_GUARD_DELAY", MIN_DELAY)


def host_cap() -> int:
    return int(number("WEB_GUARD_CAP", HOST_CAP))


def session_id(payload: dict | None = None, environ: dict | None = None) -> str:
    """The session id from a hook payload, else the harness's environment variable.
    Anything that is not a plain id comes back empty, so it can never shape a path."""
    env = os.environ if environ is None else environ
    sid = str((payload or {}).get("session_id") or env.get("CLAUDE_CODE_SESSION_ID") or "")
    return sid if SESSION_ID.match(sid) else ""


def state_root() -> str:
    return os.path.join(tempfile.gettempdir(), "web-guard-%d" % os.getuid())


def state_dir(sid: str) -> str:
    return os.path.join(state_root(), sid)


def host_of(url: str) -> str:
    """The lower-case host of an http or https address, else ''."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return parts.hostname.lower().rstrip(".")


def is_local(host: str) -> bool:
    return bool(LOCAL.match(host))


def is_strict(host: str) -> bool:
    return bool(STRICT.search(host))


def temp_roots() -> list[str]:
    roots = {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders",
             os.path.realpath(tempfile.gettempdir())}
    return sorted(roots)


def under_temp(path: str) -> bool:
    real = os.path.realpath(path)
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in temp_roots())


def below_temp(path: str) -> bool:
    """Strictly inside a temp root: a root itself is too wide to scan or to record."""
    real = os.path.realpath(path)
    return os.path.isabs(path) and under_temp(real) and real not in temp_roots()


def _empty() -> dict:
    return {"hosts": {}, "reminded_at": 0.0, "download_dirs": []}


def _own(path: str) -> None:
    """Refuse a state folder this user did not make: on a machine with a shared temp
    folder another user could plant one, or a link, under the predictable name."""
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("web-guard state folder is not a private folder of this user")


@contextmanager
def locked(sid: str):
    """The session's state as a dict, held under the lock; saved on exit when changed."""
    folder = state_dir(sid)
    for path in (state_root(), folder):           # one at a time: makedirs gives only the leaf its mode
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        _own(path)
    path = os.path.join(folder, "state.json")
    with open(os.path.join(folder, "state.lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
            if not isinstance(state, dict) or not isinstance(state.get("hosts"), dict):
                state = _empty()
        except (OSError, ValueError):
            state = _empty()
        before = json.dumps(state, sort_keys=True)
        yield state
        after = json.dumps(state, sort_keys=True)
        if after != before:
            tmp = path + ".%d.tmp" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(after)
            os.replace(tmp, path)


def read(sid: str) -> dict:
    """The state without taking the lock, for a reader that changes nothing."""
    try:
        _own(state_root())
        _own(state_dir(sid))
        with open(os.path.join(state_dir(sid), "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) and isinstance(state.get("hosts"), dict) else _empty()
    except (OSError, ValueError):
        return _empty()


def _entry(state: dict, host: str) -> dict:
    return state["hosts"].setdefault(host, {"blocked": 0, "next": 0.0, "count": 0})


def blocked(state: dict, host: str) -> int:
    """The status code that blocked the host this session, or 0."""
    return int((state.get("hosts") or {}).get(host, {}).get("blocked") or 0)


def reserve(state: dict, host: str, now: float | None = None) -> tuple[str, float]:
    """Book the next request to a host. Returns ('blocked', code), ('cap', count) or
    ('ok', seconds to wait before sending). Booking moves the host's next free time on,
    so parallel callers queue instead of sending together."""
    now = time.time() if now is None else now
    entry = _entry(state, host)
    if entry["blocked"]:
        return "blocked", float(entry["blocked"])
    if entry["count"] >= host_cap():
        return "cap", float(entry["count"])
    start = max(now, float(entry["next"]))
    entry["next"] = start + min_delay()
    entry["count"] += 1
    return "ok", start - now


def unbook(state: dict, host: str) -> None:
    """Give back a slot that reserve() booked for a request that will not be sent."""
    entry = _entry(state, host)
    entry["count"] = max(0, int(entry["count"]) - 1)
    entry["next"] = max(0.0, float(entry["next"]) - min_delay())


def refuse(state: dict, host: str, code: int) -> None:
    """Record a refusal. The first code recorded is kept; nothing clears it."""
    entry = _entry(state, host)
    if not entry["blocked"]:
        entry["blocked"] = int(code)


def reminder_due(state: dict, now: float | None = None) -> bool:
    """True when the download reminder should fire, and marks it as fired."""
    now = time.time() if now is None else now
    last = float(state.get("reminded_at") or 0.0)
    if last and now - last < number("WEB_GUARD_REMIND", REMIND_EVERY):
        return False
    state["reminded_at"] = now
    return True


def note_download_dir(state: dict, folder: str) -> None:
    """Remember a folder that received downloads, for the session-end scan. A temp root
    itself is not recorded: scanning all of it is not this session's business."""
    dirs = state.get("download_dirs")
    if not isinstance(dirs, list):
        dirs = state["download_dirs"] = []
    real = os.path.realpath(folder)
    if below_temp(real) and real not in dirs and len(dirs) < 50:
        dirs.append(real)

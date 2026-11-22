#!/usr/bin/env python3
"""Session web state shared by web_fetch_guard.py, download_guard.py, web_session_end.py
and web_download.py. Not a hook itself: it is copied beside them and loaded by path.

One small JSON file per session records, per host, whether the host refused a request,
when the next request to it may go out, and how many went out. A 401 or 403 is a
deliberate refusal and blocks the host for the session: nothing here clears it. A 429 or
503 means "not now": it blocks the host until its Retry-After time, or for TEMP_BLOCK
seconds when it gives none, held between MIN_BLOCK and MAX_BLOCK. Requests to one host are
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
import math
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

SESSION_CODES = (401, 403)  # deliberate refusals: blocked for the session
TEMP_CODES = (429, 503)     # "not now": blocked until Retry-After, else for TEMP_BLOCK
REFUSAL_CODES = SESSION_CODES + TEMP_CODES
TEMP_BLOCK = 3600.0      # seconds a 429 or 503 without Retry-After blocks its host
MIN_BLOCK = 60.0         # a Retry-After of 0 or a past date still blocks this long
MAX_BLOCK = 86400.0      # a longer Retry-After is held to a day
MIN_DELAY = 2.0          # seconds between requests to one host
HOST_CAP = 100           # requests to one host per session; a runaway-loop backstop
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
DIGITS = re.compile(r"^[0-9]{1,15}$")
# Government and military hosts: .gov and .mil, and their country forms such as gov.uk.
STRICT = re.compile(r"(^|\.)(gov|mil)(\.[a-z]{2})?$")
LOCAL = re.compile(r"^(localhost|127(\.[0-9]{1,3}){3}|::1|0\.0\.0\.0)$")


def number(name: str, default: float) -> float:
    """A tuning value from the environment; the tests shorten the delay through it. A
    non-finite value (inf, nan) gets the default."""
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def min_delay() -> float:
    return number("WEB_GUARD_DELAY", MIN_DELAY)


def host_cap() -> int:
    return int(number("WEB_GUARD_CAP", HOST_CAP))


def temp_block() -> float:
    return number("WEB_GUARD_BLOCK", TEMP_BLOCK)


def retry_after(value, now: float | None = None) -> float | None:
    """Seconds until the time a Retry-After header names, in seconds or as an HTTP date;
    None when there is no usable value."""
    text = str(value or "").strip()[:100]
    if DIGITS.match(text):                        # ASCII only: str.isdigit() passes '²', which int() rejects
        return float(min(int(text), int(MAX_BLOCK)))
    try:
        when = parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError, AttributeError):
        return None
    return when - (time.time() if now is None else now)


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
    return {"hosts": {}, "download_dirs": []}


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
    return state["hosts"].setdefault(host, {"blocked": 0, "until": 0.0, "next": 0.0, "count": 0})


def _active(entry: dict, now: float) -> int:
    """The entry's blocking code while its block holds, else 0. A 429 or 503 holds until
    its `until` time; one recorded without that time holds nothing."""
    code = int(entry.get("blocked") or 0)
    if code in TEMP_CODES and now >= float(entry.get("until") or 0):
        return 0
    return code


def blocked(state: dict, host: str, now: float | None = None) -> int:
    """The status code that blocks the host now, or 0."""
    now = time.time() if now is None else now
    return _active((state.get("hosts") or {}).get(host, {}), now)


def block_note(state: dict, host: str, now: float | None = None) -> str:
    """How long the host's block holds, for a message: 'for the session (HTTP 403)',
    'until 17:05 (Retry-After on HTTP 429)' or 'until 17:05 (1 hour after HTTP 503)'.
    '' when the host is not blocked."""
    now = time.time() if now is None else now
    entry = (state.get("hosts") or {}).get(host, {})
    code = _active(entry, now)
    if not code:
        return ""
    if code not in TEMP_CODES:
        return "for the session (HTTP %d)" % code
    until = float(entry["until"])
    stamp = time.strftime("%H:%M" if until - now < 43200 else "%Y-%m-%d %H:%M", time.localtime(until))
    if entry.get("source") == "retry-after":
        return "until %s (Retry-After on HTTP %d)" % (stamp, code)
    minutes = round(float(entry.get("window") or TEMP_BLOCK) / 60)
    span = "1 hour" if minutes == 60 else "%d minute%s" % (minutes, "" if minutes == 1 else "s")
    return "until %s (%s after HTTP %d)" % (stamp, span, code)


def reserve(state: dict, host: str, now: float | None = None) -> tuple[str, float]:
    """Book the next request to a host. Returns ('blocked', code), ('cap', count) or
    ('ok', seconds to wait before sending). Booking moves the host's next free time on,
    so parallel callers queue instead of sending together."""
    now = time.time() if now is None else now
    entry = _entry(state, host)
    code = _active(entry, now)
    if code:
        return "blocked", float(code)
    if entry["blocked"]:                          # a 429 or 503 block has lapsed
        entry.update(blocked=0, until=0.0, source="")
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


def refuse(state: dict, host: str, code: int, retry=None, now: float | None = None) -> None:
    """Record a refusal. A 401 or 403 blocks for the session; nothing clears it, and a
    later code does not replace it. A 429 or 503 blocks until the time its Retry-After
    header (`retry`) names, else for temp_block() seconds; another one while the block
    holds can only move the lift time later."""
    now = time.time() if now is None else now
    entry = _entry(state, host)
    current = _active(entry, now)
    if current and current not in TEMP_CODES:
        return
    code = int(code)
    if code not in TEMP_CODES:
        entry.update(blocked=code, until=0.0, source="")
        return
    wait = retry_after(retry, now)
    source = "default" if wait is None else "retry-after"
    wait = min(max(temp_block() if wait is None else wait, MIN_BLOCK), MAX_BLOCK)
    if current and float(entry["until"]) >= now + wait:
        return
    entry.update(blocked=code, until=now + wait, source=source, window=wait)


def note_download_dir(state: dict, folder: str) -> None:
    """Remember a folder that received downloads, for the session-end scan. A temp root
    itself is not recorded: scanning all of it is not this session's business."""
    dirs = state.get("download_dirs")
    if not isinstance(dirs, list):
        dirs = state["download_dirs"] = []
    real = os.path.realpath(folder)
    if below_temp(real) and real not in dirs and len(dirs) < 50:
        dirs.append(real)

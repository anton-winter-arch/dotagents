#!/usr/bin/env python3
"""Hooks on the page-fetch tool: remember a refusal, and space out requests to one host.

Every fetch goes out from the user's own address, so a host that refuses one must not be
asked again. This script is wired on three events of the fetch tool:

  PostToolUse, PostToolUseFailure
      When the result is a 401 or 403, the host is recorded as blocked for the session;
      a 429 or 503 blocks it for one hour (`_web_guard.py`), as this hook reads only the
      status and never a Retry-After header.
  PreToolUse
      A blocked host, or a host past its request cap, is refused: `deny` for a subagent,
      `ask` for the main session, where the user rules. Otherwise the call is booked a
      slot at least the minimum delay after the last one to that host and waits for it; a
      wait longer than MAX_WAIT seconds is refused with the time stated. A government or
      military host, in every country form `_web_guard.py` knows, is `deny` for a
      subagent and `ask` for the main session; that rule reads only the address, so it
      holds with no session id and with unusable state.

An approved `ask` does not clear a block: the next call to that host asks again until the
block lifts. Loopback hosts are not tracked. State and its lock are in
`_web_guard.py`. The hook cannot see a fetch made another way (a shell command, a browser
tool); download_guard.py covers the shell.

Fails open: any error of its own exits 0 with no output.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path

MAX_WAIT = 6.0  # seconds a call may wait for its slot inside the hook
STATUS = re.compile(r"status code (\d{3})")

BLOCKED = (
    "{host} refused an automated request earlier in this session and is blocked {note}. "
    "Make no request to this host while the block holds, do not retry it another way, and "
    "record it as unavailable."
)
CAPPED = (
    "This session has already sent {count} requests to {host}, the per-host limit. Make no "
    "further request to this host; use a source's official API or bulk download if more is "
    "needed, and say so in your reply."
)
STRICT = (
    "{host} is a government or military host. Fetching from it needs the user's yes for a "
    "specific purpose; one request, no retry after a refusal."
)
WAIT = (
    "Requests to {host} are queued {wait:.0f} seconds deep, because several calls are "
    "aimed at it at once. Do not retry now: fetch from this host one page at a time."
)


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def decision(verdict: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": verdict,
        "permissionDecisionReason": reason,
    }}))


def status_of(payload: dict) -> int:
    """The HTTP status of a fetch. After a call that returned, only the result object's
    own `code` counts: the result's text is the page, and a page that mentions a status
    must not block its host. After a call that failed, the status named in the error."""
    if payload.get("hook_event_name") == "PostToolUseFailure":
        m = STATUS.search(str(payload.get("error") or "")[:2000])
        return int(m.group(1)) if m else 0
    resp = payload.get("tool_response")
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except ValueError:
            return 0
    if isinstance(resp, dict) and isinstance(resp.get("code"), int):
        return resp["code"]
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    url = tool_input.get("url") if isinstance(tool_input, dict) else None
    if not isinstance(url, str):
        return 0
    guard = sibling("_web_guard")
    host = guard.host_of(url)
    sid = guard.session_id(payload)
    if not host or guard.is_local(host):
        return 0
    event = payload.get("hook_event_name")

    if event in ("PostToolUse", "PostToolUseFailure"):
        code = status_of(payload)
        if sid and code in guard.REFUSAL_CODES:
            with guard.locked(sid) as state:
                guard.refuse(state, host, code)
        return 0

    if event != "PreToolUse":
        return 0
    refusal = "deny" if payload.get("agent_id") else "ask"
    # The session state can be missing or unusable; the government and military rule reads
    # only the address, so it is decided either way.
    verdict, value, note = "ok", 0.0, ""
    try:
        if sid:
            with guard.locked(sid) as state:
                verdict, value = guard.reserve(state, host)
                note = guard.block_note(state, host)
                if verdict == "ok" and value > MAX_WAIT:
                    guard.unbook(state, host)     # this call is refused, so its slot goes back
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        verdict, value = "ok", 0.0
    if verdict == "blocked":
        decision(refusal, BLOCKED.format(host=host, note=note or "(HTTP %d)" % value))
    elif verdict == "cap":
        decision(refusal, CAPPED.format(host=host, count=int(value)))
    elif value > MAX_WAIT:
        decision("deny", WAIT.format(host=host, wait=value))
    else:
        if value > 0:
            time.sleep(value)
        if guard.is_strict(host):
            decision(refusal, STRICT.format(host=host))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # never block a fetch on a bug here
        print(f"web_fetch_guard error, fetch allowed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

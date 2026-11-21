#!/usr/bin/env python3
"""SessionEnd hook: scan what the session downloaded, then remove the session's web state.

When the session recorded download folders and the `local-security` command is installed,
this starts `local-security scan path <folders>` as a detached process and does not wait
for it: the session is closing, so a finding reaches the user through that tool's own
alerts, not through the agent. Files that command already judged cost nothing. Only
folders that still exist strictly inside a temp root are passed. Without the command nothing is
scanned here; the batch downloader scans during the session.

Then it removes `<system temp>/web-guard-<uid>/<session id>/`, the folder `_web_guard.py`
keeps, and nothing else. A session that ends without this event leaves that folder for the
operating system to clear.

Fails open: any error of its own exits 0 with no output.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCANNER = "local-security"
SCAN_TIMEOUT = 1800


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def start_scan(folders: list[str]) -> bool:
    """Start the scanner over the folders without waiting. False when it is not installed.
    It outlives this hook on purpose, so it runs under procguard's --detached mode: its own
    process group, stopped with everything it started after SCAN_TIMEOUT seconds."""
    program = shutil.which(SCANNER)
    if not program or not folders:
        return False
    guard = str(Path(__file__).with_name("procguard.py"))
    argv = [sys.executable, "-I", guard, "--detached", "--timeout", str(SCAN_TIMEOUT), "--",
            program, "scan", "path", *folders]
    # procguard: exempt - the watchdog itself is started here; it leads its own group and caps the scan
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "SessionEnd":
        return 0
    guard = sibling("_web_guard")
    sid = guard.session_id(payload)
    if not sid:
        return 0
    folder = guard.state_dir(sid)
    if not os.path.isdir(folder):
        return 0
    dirs = guard.read(sid).get("download_dirs")
    dirs = dirs if isinstance(dirs, list) else []
    # The state file is data any process of this user can write: only an absolute path to an
    # existing folder strictly inside a temp root is passed on, so nothing in it can become an
    # option or widen the scan.
    start_scan([os.path.realpath(d) for d in dirs
                if isinstance(d, str) and os.path.isabs(d) and os.path.isdir(d) and guard.below_temp(d)])
    # The folder is named by a validated session id under this tool's own root, and both must
    # be private folders this user owns: a planted link is never followed into a removal.
    try:
        guard._own(guard.state_root())
        guard._own(folder)
    except OSError:
        return 0
    if os.path.dirname(os.path.realpath(folder)) == os.path.realpath(guard.state_root()):
        shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # never hold a closing session on a bug here
        print(f"web_session_end error: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

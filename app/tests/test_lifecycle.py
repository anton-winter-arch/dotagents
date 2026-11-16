"""Process lifecycle: a stopped turn leaves nothing behind.

These tests start real processes - a fake CLI that starts a grandchild
and then hangs, both tagged with a per-test uuid token - and assert that a
cancel, a turn timeout and a client disconnect each leave no tokened
process alive. They never start a real agent CLI. Cleanup kills only
processes carrying this test's own token.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid

import pytest

from agents_app import app as app_module
from agents_app import chat, conversations, group

FAKE_CLI = """#!{python}
import json, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", "{token}"])
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "s-1"}}), flush=True)
time.sleep(300)
"""


def tokened(token: str) -> list[int]:
    """Pids whose command line carries the token (ps, never by name)."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,stat=,command="],
                         capture_output=True, text=True, timeout=10).stdout
    pids = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and token in parts[2] and not parts[1].startswith("Z"):
            pids.append(int(parts[0]))
    return pids


def wait_for(predicate, limit: float = 15.0) -> bool:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


@pytest.fixture
def token():
    value = f"lifecycle-{uuid.uuid4().hex}"
    yield value
    for pid in tokened(value):  # only this test's own processes
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture
def fake_cli(tmp_path, token, monkeypatch):
    # The token rides the CLI's own path too, so the CLI, not only its
    # grandchild, is checked and cleaned up.
    path = tmp_path / f"fake-cli-{token}"
    path.write_text(FAKE_CLI.format(python=sys.executable, token=token))
    path.chmod(0o755)
    monkeypatch.setenv("AGENTS_APP_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(chat, "claude_cli", lambda: str(path))
    monkeypatch.setattr(chat, "harness_bin",
                        lambda name: str(path) if name == "cursor" else None)
    group._cancel_requested.clear()
    return path


async def _cancel_once_running(cid: str, token: str) -> None:
    loop = asyncio.get_running_loop()
    seen = await loop.run_in_executor(None, wait_for, lambda: tokened(token))
    assert seen, "the fake CLI never started its grandchild"
    group._cancel_requested.add(cid)


def _run(lane, cid=None, token=None):
    async def go():
        consumer = asyncio.ensure_future(_collect(lane))
        if cid is not None:
            await _cancel_once_running(cid, token)
        return await asyncio.wait_for(consumer, 60)
    return asyncio.run(go())


async def _collect(lane):
    return [frame async for frame in lane]


def _seat(cid, tmp_path, harness="claude"):
    cwd = tmp_path / "seat"
    cwd.mkdir(exist_ok=True)
    return conversations.add_participant(cid, "Scout", str(cwd),
                                         harness=harness)


def test_cancel_leaves_no_tokened_process(fake_cli, token):
    cid = conversations.create()["id"]
    frames = _run(chat._claude_code_lane("go", cid, turn_timeout=60),
                  cid, token)
    assert any(b"interrupted" in frame for frame in frames)
    assert wait_for(lambda: not tokened(token), 5), tokened(token)


def test_seat_timeout_leaves_no_tokened_process(fake_cli, token, tmp_path):
    cid = conversations.create()["id"]
    seat = _seat(cid, tmp_path)
    frames = _run(chat._claude_code_lane("go", cid, seat=seat,
                                         turn_timeout=3))
    assert any(b"exceeded" in frame for frame in frames)
    assert wait_for(lambda: not tokened(token), 5), tokened(token)


def test_peer_seat_timeout_leaves_no_tokened_process(fake_cli, token, tmp_path):
    cid = conversations.create()["id"]
    seat = _seat(cid, tmp_path, harness="cursor")
    frames = _run(chat._peer_harness_lane("go", cid, seat, turn_timeout=3))
    assert any(b"exceeded" in frame for frame in frames)
    assert wait_for(lambda: not tokened(token), 5), tokened(token)


def test_disconnect_leaves_no_tokened_process(fake_cli, token):
    """A client that goes away: the server cancels the task streaming the
    turn, the way Starlette does on disconnect."""
    cid = conversations.create()["id"]

    async def go():
        consumer = asyncio.ensure_future(
            _collect(chat._claude_code_lane("go", cid, turn_timeout=60)))
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, wait_for,
                                          lambda: tokened(token))
        consumer.cancel()
        try:
            await asyncio.wait_for(consumer, 60)
        except asyncio.CancelledError:
            pass
    asyncio.run(go())
    assert wait_for(lambda: not tokened(token), 5), tokened(token)


def test_main_lane_gets_the_configured_turn_cap(monkeypatch):
    """The two-party lane is capped too: stream_chat passes turn_timeout."""
    seen = {}

    async def lane(message, conversation_id, **kwargs):
        seen.update(kwargs)
        yield chat.sse("done", {})

    monkeypatch.setattr(chat, "_claude_code_lane", lane)
    monkeypatch.setattr(chat, "pick_lane", lambda: "claude_code")
    monkeypatch.setenv("AGENTS_APP_TURN_TIMEOUT", "900")
    cid = conversations.create()["id"]
    asyncio.run(_collect(chat.stream_chat("hi", cid)))
    assert seen["turn_timeout"] == 900.0


def test_spawn_env_disables_background_tasks():
    assert chat._cli_env()["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"


def test_cmd_down_leaves_a_recycled_pid_alone(tmp_path, monkeypatch, token):
    """A stale pid file whose number now leads another program's group: down
    removes the file and signals nothing."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", token],
                             start_new_session=True)
    try:
        assert wait_for(lambda: tokened(token)), "the stand-in never started"
        monkeypatch.setenv("AGENTS_APP_HOME", str(tmp_path))
        (tmp_path / "pid").write_text(f"{other.pid}\n8765\n")
        monkeypatch.setattr(app_module, "_release_local_models", lambda: None)
        assert app_module.cmd_down() == 0
        assert other.poll() is None, "down signaled a group it does not own"
        assert not (tmp_path / "pid").exists()
    finally:
        other.kill()
        other.wait(timeout=10)


def test_cmd_down_stops_a_group_whose_leader_died(tmp_path, monkeypatch, token):
    """The leader exits and is reaped; a member it started lives on in
    its group. down probes and signals the group, not the dead pid."""
    leader = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys; subprocess.Popen([sys.executable, '-c', "
         f"'import time; time.sleep(300)', '{token}'])"],
        start_new_session=True)
    leader.wait(timeout=10)
    assert wait_for(lambda: tokened(token)), "the member never started"
    monkeypatch.setenv("AGENTS_APP_HOME", str(tmp_path))
    (tmp_path / "pid").write_text(f"{leader.pid}\n8765\n")
    monkeypatch.setattr(app_module, "_release_local_models", lambda: None)

    assert app_module.cmd_down() == 0
    assert wait_for(lambda: not tokened(token), 5), tokened(token)
    assert not (tmp_path / "pid").exists()

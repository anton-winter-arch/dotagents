#!/usr/bin/env python3
"""PreToolUse hook on the shell: who may fetch from the web there, and that every file
download goes through the batch downloader, which scans what it fetched.

A shell fetch goes out from the user's own address and nothing paces or remembers it, so
the rules are these, for each simple command whose program is `curl` or `wget`, a Python
one-liner that fetches an address, or a run of `web_download.py`:

  A subagent        is refused any fetch from a host that is not loopback. It reads pages
                    with the fetch tool, and for files it returns a manifest's path, never a
                    command; the main session runs the downloader on it, and a downloader
                    run with --no-scan gets `ask`.
  The main session  gets `ask` when the fetch imitates a browser, uses an impersonation
                    tool, names a proxy or is piped straight into a shell; when the host
                    is a government or military one; or when the host refused a request
                    earlier in this session.
  A download        (an output option, or a redirect of the output into a file) from a host
                    that is not loopback is refused in the main session too: the refusal
                    names the web_download.py line to run instead, or, when the target is
                    under the user's Downloads, Desktop or Documents folder or inside a git
                    repository, says why that place is wrong.

The program is read the way deny_debugger_attach.py reads it (wrappers unwrapped, quoted
text whole, here-document bodies left out), so a command that only mentions these words
passes. A Python program fed on a here-document is read from its body. An address held in
a variable, a fetch inside a script file, a `bash -c` string, where a Python fetch writes
its file, and a fetch piped into `tar` are not seen: this guards the honest case. A command with none of the fetch words exits in
the first lines, before any other module is loaded.

Fails open: any error of its own exits 0 with no output.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

QUICK = ("curl", "wget", "web_download.py", "urllib", "requests", "httpx")
FETCHERS = {"curl", "wget"}
PYTHONS = re.compile(r"^python[0-9.]*$")
PY_FETCH = re.compile(r"\b(urllib\.request|urlretrieve|urlopen|requests\.|httpx\.)")
ADDRESS = re.compile(r"https?://[^\s'\"<>)\]]+")
BROWSER = re.compile(r"(Mozilla|Chrome|Safari|Firefox|AppleWebKit)/")
IMPERSONATORS = re.compile(r"^(curl_cffi|curl-impersonate.*|curl_(chrome|ff|safari|edge)[0-9a-z_]*)$")
PROXY_ENV = re.compile(r"^(https?_proxy|all_proxy)=", re.I)
CURL_PROXY = {"-x", "--proxy", "--preproxy", "--socks4", "--socks4a", "--socks5", "--socks5-hostname"}
CURL_VALUE = {"-A", "--user-agent", "-H", "--header", "-o", "--output", "--output-dir", "-d", "--data",
              "-e", "--referer", "-b", "--cookie", "-u", "--user", "-X", "--request", "-w", "--write-out",
              "-m", "--max-time", "--connect-timeout", "--retry", "-F", "--form", "-c", "--cookie-jar",
              "-T", "--upload-file", "--data-raw", "--data-binary", "--data-urlencode", "-r", "--range"}
REDIRECT = re.compile(r"^([0-9]*|&)(>>?)(.*)$")
HEREDOC_PYTHON = re.compile(r"\bpython[0-9.]*\b[^\n|;&]*<<")
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b(?:[^|;&\n]|>&|&>)*\|[ \t]*(sudo[ \t]+)?(ba|z|da)?sh\b")
PERSONAL = ("Downloads", "Desktop", "Documents")
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until"}
MAX_COMMAND = 32_000

SUBAGENT = (
    "Blocked: a subagent does not fetch from the web in the shell ({host}). Every request "
    "there leaves from the user's own address, unpaced. Read pages with the fetch tool. For "
    "files, write a manifest (one JSON object per line: url, name, why) in the scratch "
    "folder, end your report with the manifest's path, and stop. The main session runs "
    "the batch downloader on that path, which scans what it fetched; an ordinary batch "
    "needs no approval from the user."
)
EVASION = (
    "This fetch {what}. Agents do not disguise a request or route it around a site's "
    "filtering. Approve only if this is honest access the user asked for."
)
STRICT = (
    "{host} is a government or military host. Fetching from it needs the user's yes for a "
    "specific purpose; one request, no retry after a refusal."
)
REFUSED = (
    "{host} refused an automated request earlier in this session (HTTP {code}). A refusal "
    "is final for the session; approve only if the user wants this one request sent anyway."
)
UNSCANNED = (
    "This batch download skips its scan, so its files reach the session unchecked. "
    "Approve only if the user asked for that."
)
PLACE = (
    "Blocked: this download would land in {where}. Agent downloads go in the session "
    "scratch folder, never in a repository or the user's own folders. Download there, scan "
    "it, and copy what is wanted afterwards."
)
ONE_WAY = (
    "Blocked: files are downloaded only through the batch downloader, which paces requests, "
    "stops at a refusal, keeps the files in session scratch and scans them once. Write a "
    "manifest (one JSON object per line: url, name, why) in the scratch folder, then run: "
    "python3 {downloader} <manifest path>. Reading a page to standard output stays allowed."
)


def sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def downloader() -> str:
    """The batch downloader beside this hook, written with `~` for the home folder."""
    path = str(Path(__file__).with_name("web_download.py"))
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def expand(path: str) -> str:
    """A path with `~`, $HOME and $TMPDIR expanded; '' when another variable is in it."""
    home = os.path.expanduser("~")
    tmp = os.environ.get("TMPDIR", "/tmp")
    for var, value in (("${HOME}", home), ("$HOME", home), ("${TMPDIR}", tmp), ("$TMPDIR", tmp)):
        path = path.replace(var, value)
    if "$" in path or "`" in path:
        return ""
    return os.path.expanduser(path)


def in_repo(folder: str) -> bool:
    cur = os.path.realpath(folder)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def bad_place(folder: str, guard) -> str:
    """Why a download may not land in this folder, or ''."""
    if guard.under_temp(folder):
        return ""
    real = os.path.realpath(folder)
    home = os.path.realpath(os.path.expanduser("~"))
    for name in PERSONAL:
        root = os.path.join(home, name)
        if real == root or real.startswith(root + "/"):
            return "the user's %s folder" % name
    return "a git repository" if in_repo(real) else ""


class Call:
    """One fetch command: its hosts, whether it downloads, where to, and how it is dressed."""

    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.download = False
        self.target = ""      # the folder a download lands in, '' when unknown
        self.dressed = ""     # how the request is disguised or rerouted, '' when it is not
        self.batch = False    # a web_download.py run
        self.unscanned = False  # a web_download.py run with --no-scan


def folder_of(cwd: str, value: str) -> str:
    """The folder a file argument lands in, '' when the argument holds an unknown variable."""
    path = expand(value)
    return os.path.dirname(os.path.join(cwd, path)) if path else ""


def add_host(call: Call, word: str, guard) -> None:
    """Record the host of an address argument. A bare word with no dot and no colon is not
    an address (a stream number left over from a redirect, a stray operand)."""
    host = guard.host_of(word if "://" in word else "http://" + word)
    if host and (host == "localhost" or "." in host or ":" in host):
        call.hosts.append(host)


def redirect_at(call: Call, args: list[str], i: int, cwd: str, out: dict) -> int:
    """How many words a redirect starting at args[i] uses, 0 when there is none. The
    tokenizer splits `2>file` into `2` and `>file`, so a number followed by a `>` word is
    read as one redirect of that stream."""
    word = args[i]
    after = args[i + 1] if i + 1 < len(args) else ""
    if word.isdigit() and after.startswith(">"):
        return 1 + take_redirect(call, word + after, args[i + 2] if i + 2 < len(args) else "", cwd, out)
    return take_redirect(call, word, after, cwd, out)


def take_redirect(call: Call, word: str, nxt: str, cwd: str, out: dict) -> int:
    """Read `> file`, `>> file` or `>file` as the download's target. Returns how many
    words the redirect used, 0 when the word is not one. An error stream, a duplicated
    descriptor and /dev/null are not downloads."""
    m = REDIRECT.match(word)
    if not m:
        return 0
    stream, path = m.group(1), m.group(3) or nxt
    if m.group(3) == "&":                         # `>& 2`: a duplicated descriptor and its number
        return 2
    if stream in ("", "1", "&") and path and not path.startswith("&") and path != "/dev/null":
        call.download = True
        out["redirect"] = folder_of(cwd, path)
    return 1 if m.group(3) else 2


def curl_flag(call: Call, flag: str, value: str, cwd: str, out: dict) -> None:
    """Apply one curl option, short or long, with its value."""
    if flag in CURL_PROXY:
        call.dressed = "names a proxy"
    elif flag == "--impersonate":
        call.dressed = "impersonates a browser"
    elif flag in ("-A", "--user-agent", "-H", "--header") and BROWSER.search(value):
        call.dressed = "sends a browser's User-Agent"
    elif flag in ("-o", "--output") and value not in ("-", "/dev/null"):
        call.download = True
        out["file"] = value
    elif flag == "--output-dir":
        out["dir"] = expand(value)
    elif flag in ("-O", "--remote-name", "--remote-name-all"):
        call.download = True


def read_curl(args: list[str], cwd: str, guard) -> Call:
    call = Call()
    out: dict = {}
    takes_value = CURL_VALUE | CURL_PROXY | {"--impersonate"}
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else ""
        if a.startswith("--"):
            flag, _, attached = a.partition("=")
            curl_flag(call, flag, attached or nxt, cwd, out)
            if flag in takes_value and not attached:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            letters = a[1:]
            for pos, ch in enumerate(letters):
                flag, rest = "-" + ch, letters[pos + 1:]
                if flag in takes_value:
                    curl_flag(call, flag, rest or nxt, cwd, out)
                    if not rest:
                        i += 1
                    break
                curl_flag(call, flag, "", cwd, out)
        else:
            used = redirect_at(call, args, i, cwd, out)
            if used:
                i += used
                continue
            add_host(call, a, guard)
        i += 1
    if call.download:
        base = os.path.join(cwd, out["dir"]) if out.get("dir") else cwd
        call.target = folder_of(base, out["file"]) if out.get("file") else base
        if "redirect" in out:
            call.target = out["redirect"]
    return call


def read_wget(args: list[str], cwd: str, guard) -> Call:
    call = Call()
    call.download = True
    call.target = cwd
    out: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else ""
        flag, _, attached = a.partition("=") if a.startswith("--") else (a, "", "")
        short = a.startswith("-") and not a.startswith("--") and len(a) > 1
        used = 0 if a.startswith("-") else redirect_at(call, args, i, cwd, out)
        if used:
            call.target = out.get("redirect", call.target)
            i += used
            continue
        if flag == "--spider":
            call.download = False
        elif flag == "--output-document" or (short and "O" in a):
            value = attached or (a.split("O", 1)[1] if short else "")
            if not value:
                value, i = nxt, i + 1
            if value in ("-", "/dev/null"):
                call.download = False
            else:
                call.target = folder_of(cwd, value)
        elif flag in ("-P", "--directory-prefix"):
            value = attached
            if not value:
                value, i = nxt, i + 1
            call.target = os.path.join(cwd, expand(value)) if expand(value) else ""
        elif flag in ("-U", "--user-agent"):
            value = attached
            if not value:
                value, i = nxt, i + 1
            if BROWSER.search(value):
                call.dressed = "sends a browser's User-Agent"
        elif flag in ("-e", "--execute"):
            value = attached
            if not value:
                value, i = nxt, i + 1
            if "proxy" in value:
                call.dressed = "names a proxy"
        elif not a.startswith("-"):
            add_host(call, a, guard)
        i += 1
    return call


def read_python(args: list[str], guard) -> Call | None:
    for n, a in enumerate(args):
        if a.rsplit("/", 1)[-1] == "web_download.py":
            call = Call()
            call.batch = True
            # A host passed with --allow-host is judged like a direct fetch to it.
            for m, flag in enumerate(args[n + 1:], start=n + 1):
                value = flag.partition("=")[2] or (args[m + 1] if m + 1 < len(args) else "")
                if flag.partition("=")[0] == "--allow-host" and value:
                    call.hosts.append(value.lower())
                if flag == "--no-scan":
                    call.unscanned = True
            return call
    code = " ".join(args)
    if not PY_FETCH.search(code):
        return None
    call = Call()
    call.hosts = [h for h in (guard.host_of(u) for u in ADDRESS.findall(code)) if h]
    if BROWSER.search(code):
        call.dressed = "sends a browser's User-Agent"
    return call if call.hosts else None


def calls_in(command: str, cwd: str, guard) -> list[Call]:
    debugger = sibling("deny_debugger_attach")
    segments = sibling("guard_git_bypass").segments
    found: list[Call] = []
    for words in segments(debugger.without_heredocs(command)):
        while words and words[0] in KEYWORDS:     # a loop or branch body: `do curl ...`, `then wget ...`
            words = words[1:]
        prog = debugger.program_of(words)
        if prog == "cd" and len(words) > 1 and expand(words[-1]):
            cwd = os.path.join(cwd, expand(words[-1]))
            continue
        at = next((n for n, w in enumerate(words) if w.rsplit("/", 1)[-1].lower() == prog), None)
        if at is None:
            continue
        args = words[at + 1:]
        call = None
        if IMPERSONATORS.match(prog):
            call = read_curl(args, cwd, guard)
            call.dressed = "uses an impersonation tool"
        elif prog == "curl":
            call = read_curl(args, cwd, guard)
        elif prog == "wget":
            call = read_wget(args, cwd, guard)
        elif PYTHONS.match(prog) or prog == "uv":
            call = read_python(args, guard)
        if call is None:
            continue
        if any(PROXY_ENV.match(w) for w in words[:at]):
            call.dressed = "names a proxy"
        found.append(call)
    # A Python program fed on a here-document, `python3 - <<'EOF'`: its body was left out
    # above, so the fetch is read from the whole command text.
    if HEREDOC_PYTHON.search(command) and PY_FETCH.search(command):
        call = Call()
        call.hosts = [h for h in (guard.host_of(u) for u in ADDRESS.findall(command)) if h]
        if BROWSER.search(command):
            call.dressed = "sends a browser's User-Agent"
        if call.hosts:
            found.append(call)
    # A fetch piped into a shell is marked on the call that fetches: the one whose address
    # is in the piped text, else the first call to a host that is not loopback.
    for piped in PIPE_TO_SHELL.finditer(debugger.without_heredocs(command)) if found else ():
        hosts = {guard.host_of(u) for u in ADDRESS.findall(piped.group(0))}
        call = next((c for c in found if hosts & set(c.hosts)), None) or \
            next((c for c in found if any(not guard.is_local(h) for h in c.hosts)), None)
        if call is not None and not call.dressed:
            call.dressed = "pipes what it fetches straight into a shell, which runs downloaded code"
    return found


def emit(payload: dict) -> None:
    print(json.dumps({"hookSpecificOutput": dict(payload, hookEventName="PreToolUse")}))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse":
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or len(command) > MAX_COMMAND:
        return 0
    if not any(word in command for word in QUICK):
        return 0

    guard = sibling("_web_guard")
    cwd = str(payload.get("cwd") or os.getcwd())
    calls = calls_in(command, cwd, guard)
    if not calls:
        return 0
    sid = guard.session_id(payload)
    state = guard.read(sid) if sid else {"hosts": {}}

    deny = ask = ""
    for call in calls:
        remote = [h for h in call.hosts if not guard.is_local(h)]
        if payload.get("agent_id"):
            if remote or call.batch:
                deny = deny or SUBAGENT.format(host=remote[0] if remote else "a batch download")
            continue
        if call.unscanned:
            ask = ask or UNSCANNED
        if not remote:
            continue
        if call.dressed:
            ask = ask or EVASION.format(what=call.dressed)
        for host in remote:
            if guard.is_strict(host):
                ask = ask or STRICT.format(host=host)
            elif guard.blocked(state, host):
                ask = ask or REFUSED.format(host=host, code=guard.blocked(state, host))
        if call.download:
            where = bad_place(call.target, guard) if call.target else ""
            deny = deny or (PLACE.format(where=where) if where else ONE_WAY.format(downloader=downloader()))

    if deny:
        emit({"permissionDecision": "deny", "permissionDecisionReason": deny})
    elif ask:
        emit({"permissionDecision": "ask", "permissionDecisionReason": ask})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # never brick the shell on a bug here
        print(f"download_guard error, command allowed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(0)

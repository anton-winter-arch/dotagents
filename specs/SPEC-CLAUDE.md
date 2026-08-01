# SPEC-CLAUDE.md - Claude Code Station Seed

This spec contains my standard configuration for Claude Code. 
It can be followed to to stand up a new device or align an existing one. 
This repo (`~/.agents`) is the source of truth for my global, cross-device skills/agents/commands; 
this file is the source of truth for everything *around* them - plugins, CLI deps, global rules, hooks, and settings. 
These configs exist to improve the consistency, reliability, and security of my Claude Code environment. 

**Contract for any agent reading this:** if you are working in this repo, grabbing the global skills, or seeding a new machine, bring the station into line with this spec - *non-destructively*. Diff before you touch anything that already exists, show what would change, and get approval before overwriting. 
Edits under `~/.claude` will trigger an "ask" permission prompt by design (see §7) - that is the system working, not an error. Everything here is idempotent: a fully set-up station requires zero changes.

**No personal constants.** This spec (and everything it seeds) contains no names, emails, handles, personal repo URLs, or device-specific paths. 
Anything personal (env, `git config`, session context, etc.) is derived per user at runtime or asked of the user live. Keep this file that way when editing.

---

## 0. The templates

Every file this spec seeds lives under [`claude-code/`](claude-code/) as a real
file rather than a code block, so it can be diffed, linted and copied directly:

| File | Goes to | Section |
|---|---|---|
| [`CLAUDE.md`](claude-code/CLAUDE.md) | `~/.claude/CLAUDE.md` | [5](#5-global-claudeclaudemd-template) |
| [`RTK.md`](claude-code/RTK.md) | `~/.claude/RTK.md` | [6](#6-global-claudertkmd-template) |
| [`settings.json`](claude-code/settings.json) | `~/.claude/settings.json` | [7](#7-global-claudesettingsjson---rules-in-principle-then-the-template) |
| [`hooks/`](claude-code/hooks) | `~/.claude/hooks/` | [8](#8-hook-scripts-claudehooks) |
| [`statusline.sh`](claude-code/statusline.sh) | `~/.claude/statusline.sh` | [9](#9-status-lines-claudestatuslinesh--subagent-statuslinesh) |
| [`keybindings.json`](claude-code/keybindings.json) | `~/.claude/keybindings.json` | [10](#10-keybindings-claudekeybindingsjson--terminal-setup) |

**Most readers want [`claude-code/CLAUDE.md`](claude-code/CLAUDE.md)** - the
global rules file. The sections below say what each file is for and why it is
shaped that way; the files themselves are the thing you copy.

Keep the two in parity: these files and a configured station should match
byte for byte, so a drift check is a `diff` rather than a reading exercise.

## 1. Target state (what "set up" means)

| Piece | Location | Source |
|---|---|---|
| Claude Code CLI | `claude` on PATH | official installer |
| This repo | `~/.agents` (git clone) | remote |
| Skills/agents/commands symlinks | `~/.claude/skills`, `~/.claude/agents`, `~/.claude/commands` | `bash ~/.agents/sync-skills.sh` |
| Global instructions | `~/.claude/CLAUDE.md` + `~/.claude/RTK.md` | templates in §5 and §6 |
| Global settings | `~/.claude/settings.json` | template in §7 |
| Hook scripts | `~/.claude/hooks/*.sh` | embedded in §8 |
| Status line | `~/.claude/statusline.sh` | embedded in §9 |
| Subagent status line | `~/.claude/subagent-statusline.sh` | embedded in §9 |
| Keybindings | `~/.claude/keybindings.json` | embedded in §10 |
| Plugins (4) | installed + enabled in Claude Code | §3 |
| rtk | `/opt/homebrew/bin/rtk` (or PATH) | `brew install rtk-ai/tap/rtk` |
| claude-mem daemon | `localhost:37701` | comes with the claude-mem plugin |

## 2. CLI dependencies

- **Claude Code** - the harness itself.
- **git** + **gh** - repo sync and GitHub operations.
- **jq** - **required**: both hook scripts in §8 parse tool-call JSON with it.
  Hooks fail silently without it. `brew install jq`.
- **rtk** (Rust Token Killer) - token-optimizing CLI proxy, wired in as a
  PreToolUse hook on Bash (§7). `brew install rtk-ai/tap/rtk`
  (tap: `rtk-ai/tap`; the formula shadows `homebrew/core/rtk` - verify with
  `rtk gain`, and see `~/.claude/RTK.md` for the name-collision warning).
  Seed its config with `rtk config --create`, then in the generated
  `config.toml` (macOS: `~/Library/Application Support/rtk/config.toml`) set
  `[hooks] exclude_commands = ["grep"]` - rtk's grep filter can elide the
  actual match lines ("N matches in 0 files"), so grep runs raw while every
  other filter stays on. Escape hatch for any command: `rtk proxy <cmd>`
  (dry-run what the hook would do: `rtk hook check '<cmd>'` - note it exits
  1 when the command would NOT be rewritten, so append `|| true` when
  chaining checks with `&&`; rtk ≥0.43.0).
- **node / npx** - claude-mem's daemon and `npx claude-mem` CLI.
- **python3** - several skills in this repo bundle python scripts/tests.

## 3. Plugins & marketplaces

Add marketplaces, then install, inside Claude Code (`/plugin`):

| Plugin | Marketplace (GitHub) | Purpose |
|---|---|---|
| `claude-mem@thedotmack` | `thedotmack/claude-mem` | persistent memory daemon: semantic search, timeline, observation capture; web UI at `http://localhost:37701`; config `~/.claude-mem/settings.json` |
| `agent-skills@addy-agent-skills` | `addyosmani/agent-skills` | senior-engineer workflow skills (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/ship`, …) - mandated for every engineering task by the global CLAUDE.md |
| `skill-creator@claude-plugins-official` | `anthropics/claude-plugins-official` | scaffolding + evals when authoring new skills (pairs with this repo's `skill-authoring` skill) |
| `mcp-server-dev@claude-plugins-official` | `anthropics/claude-plugins-official` | first-party (Anthropic) skills for building MCP servers/apps (`build-mcp-server`, `build-mcp-app`, `build-mcpb`) - the deferral target named by this repo's `ai-engineering` skill; pure knowledge plugin, zero deps/hooks/runtime |

Enablement lives in `settings.json → enabledPlugins` (§7). Keep
`thedotmack` on auto-update; pin/refresh the others deliberately.

### 3.1 claude-mem - disable its file-read interception (REQUIRED)

**The gotcha:** out of the box, claude-mem registers a `PreToolUse` hook on
`Read` (and processes `Grep`/`Glob`/web tools) that intercepts the call and
feeds the agent a *summary* instead of the actual file. An agent that cannot
read a file verbatim is a broken agent - this silently blinds it. It is on by
default the moment you install the plugin.

**The fix** is claude-mem's own `CLAUDE_MEM_SKIP_TOOLS` - the list of tools it
must leave alone. Seed `~/.claude-mem/settings.json` (claude-mem's config, NOT
the plugin cache - so it survives auto-update) with **Read/Glob/Grep and the
retrieval tools added to the skip list**:

```json
{
  "CLAUDE_MEM_RUNTIME": "worker",
  "CLAUDE_MEM_SKIP_TOOLS": "ListMcpResourcesTool,SlashCommand,Skill,TodoWrite,AskUserQuestion,Read,Glob,Grep,ToolSearch,WebSearch,WebFetch"
}
```

This keeps everything worth keeping - SessionStart context injection, the MCP
search (`smart_search`/`smart_outline`/`smart_unfold`), PostToolUse observation
capture on the tools that stay in scope - while stopping claude-mem from
standing between the agent and the filesystem. Add more `mcp__*` entries if a
future claude-mem version starts intercepting other read-shaped tools.

**Durability note:** this file is per-machine and unversioned by claude-mem, so
a fresh install or reinstall reverts to the blinding default. It is a bootstrap
step (§11) precisely so every station re-seeds it; verify it after any
claude-mem reinstall.

## 4. This repo (`~/.agents`)

Clone the skills repo to `~/.agents`, then:

```bash
bash ~/.agents/sync-skills.sh
```

That symlinks `skills/` → `~/.claude/skills`, `agents/` → `~/.claude/agents`,
`commands/` → `~/.claude/commands` (per-entry links; idempotent;
non-destructive to device-local entries). Branch model: work on `develop`,
fast-forward `main`. Read `AGENTS.md` before changing anything in the repo.

## 5. Global `~/.claude/CLAUDE.md` template

Seed verbatim (it imports RTK.md via the trailing `@RTK.md` line, so §6 must
exist too):

Seed it verbatim from [`claude-code/CLAUDE.md`](claude-code/CLAUDE.md).

## 6. Global `~/.claude/RTK.md` template

Seed it verbatim from [`claude-code/RTK.md`](claude-code/RTK.md).

## 7. Global `~/.claude/settings.json` - rules in principle, then the template

The principles each block enforces:

1. **Privacy/telemetry off** - no telemetry, error reporting, feedback
   surveys, or non-essential model calls.
2. **No AI attribution** - empty `attribution` strings keep commits and PRs
   free of generated-by lines.
3. **Secrets are unreachable** - `permissions.deny` blocks every file tool
   from `.env` files; the `block-env-files.sh` hook (§8) extends the same
   guarantee to arbitrary Bash commands and tells the model to stop and ask
   rather than work around it. Conventional non-secret variants
   (`.env.example` etc.) stay allowed.
4. **Token efficiency at the tool boundary** - `rtk hook claude` on every
   Bash call transparently rewrites commands through rtk.
5. **The shell is not a file editor** - `deny-bash-file-writes.sh` denies
   shell file-authoring (redirects, `tee`, `sed -i`, interpreter writes,
   heredoc-to-file) and `guard-rm.sh` denies/asks on destructive `rm`, both
   on the Bash matcher (§8). File content goes through Write/Edit, deletion
   through `mv` to `__archive/` - the paths that carry diff review and
   `/rewind` checkpointing, which shell writes/deletes silently bypass.
   One scoped exception: `>`/`>>` into the session scratchpad tree, where
   neither protection has anything to protect.
6. **Global config is guarded** - any Write/Edit inside `~/.claude` is forced
   to an "ask" permission prompt (`ask-before-claude-folder-edits.sh`), so
   nothing silently changes how every session behaves.
7. **No remote control** - `disableRemoteControl` keeps sessions
   local-only.
8. **Device preferences** - `model` and `theme` are per-device taste, not
   policy; adjust freely. The `statusLine` and `subagentStatusLine` blocks
   point at the scripts seeded from §9; keep each block and its script
   together (both present or both dropped).

Template:

The template is [`claude-code/settings.json`](claude-code/settings.json).

If a `settings.json` already exists on the device, **merge, don't replace** -
diff against this template, show the delta, get approval (non-destructive
rule + §7.6's own hook both apply).

### Secrets out of agent context (extends §7 principle 3)

Extends principle 3. A separate leak path from git: a repo with a clean
`.gitignore` can still hand `.env`, private keys, or cloud creds to an agent
that reads them off disk (or a cloud/OSS model behind a tool call). The rule:

1. **Secrets must never reach an AI/agent's context** - `.env`, private keys,
   service-account JSON, tokens, tfstate.
2. **Ignore files are defense-in-depth, not a security boundary.** Verified
   2026-07: most agent "ignore" files are best-effort or discovery-only and
   bypassable via `@`-mention, `cat`/`rg`, or a subprocess. The only HARD
   controls are permission/deny systems and OS sandboxing.
3. **The real fix is upstream:** keep long-lived high-value secrets out of the
   repo entirely (runtime env injection / a secrets manager) and rotate.
   Ignore files only reduce casual re-exposure.

Per-tool reality (which control is real vs theater), verified 2026-07:

| Control | Tool | Enforcement |
|---|---|---|
| `permissions.deny` in `.claude/settings.json` (+ `block-env-files.sh`) | Claude Code | **HARD - use this** |
| `deny` in `~/.codex/config.toml` | Codex CLI | **HARD - use this** |
| `.cursorignore` | Cursor | official, best-effort |
| `.aiexclude` | Gemini Code Assist / Firebase / Android Studio | official, overrides `.gitignore` |
| `.geminiignore` | Gemini CLI | official, discovery-only |
| `.gooseignore` | Goose | official, Developer-extension only |
| `.claudeignore` | Claude Code | **NOT read - forward-compat only** (see below) |
| `.codexignore` | Codex CLI | not reliably honored - forward-compat |
| `.agentignore` / `.aiignore` | cross-tool | unratified proposal, honored by nothing |
| Content exclusion | GitHub Copilot | org/enterprise web-UI only; no in-repo file |

`.claudeignore` is a **widely-assumed file that Claude Code does not read**
(verified 2026-07; The Register 2026-01-28 reproduced Claude Code reading a
`.env` despite a `.claudeignore` entry). Ship it only as forward-compat with
an honest header; the hard control on this station is the §7 `.env` deny set
plus `block-env-files.sh` (§8).

**Per-repo baseline:** confirm `.gitignore` covers `.env*`; add a hard deny
rule for whichever agent(s) that repo uses; and (optional, defense-in-depth)
drop the canonical exclusion list into the real ignore files for the tools in
use. The canonical list and the honest per-tool header conventions live in
`AGENTS.md` (repo-working standard) so any repo can copy them.

## 8. Hook scripts (`~/.claude/hooks/`)

Eight hooks: three Bash-write/delete guards (`deny-bash-file-writes.sh`,
`guard-rm.sh`, `block-env-files.sh`), the `~/.claude`-edit prompt
(`ask-before-claude-folder-edits.sh`), the SessionStart inbox check
(`agent-mail-check.sh`), the large-file read advisory
(`read-size-advisory.sh`), and the two memory-write guards
(`memory-routing.sh` advisory-routing + `memory_lint.py` post-write lint).
Three are advisory/non-blocking (`read-size-advisory`, `memory-routing`, and
`memory_lint`'s judgment checks); the rest can block. All shell hooks require
`jq`; the two quote-aware guards also require `perl`; `memory_lint.py` is
stdlib python3 (all §2 deps). Seed verbatim.

### `block-env-files.sh`

Script: [`claude-code/hooks/block-env-files.sh`](claude-code/hooks/block-env-files.sh).

### `ask-before-claude-folder-edits.sh`

Script: [`claude-code/hooks/ask-before-claude-folder-edits.sh`](claude-code/hooks/ask-before-claude-folder-edits.sh).

### `deny-bash-file-writes.sh`

PreToolUse guard (matcher `Bash`, wired in §7): **denies** any Bash command
that authors file content via the shell - output redirects (`>`/`>>`/`&>`,
after boundary-safe scrubbing of `/dev/null` sinks and fd duplications),
`tee`, `sed`/`gsed`/`perl` in-place edits (bundled flags like `-pi`
included), python `open()` write/append/exclusive-create modes, pathlib
`write_text`/`write_bytes`, node `writeFile`/`appendFile(Sync)`, heredoc-fed
`git apply`/`patch`, `dd of=`, and `truncate`. Deny, not ask: the agent does
not get a dialog to approve its own bypass. The deny reason steers the agent
to the right path (Write/Edit tools; read program output from stdout; or
hand a genuine output-to-disk need to the user) and states why: shell writes
bypass diff review, the `~/.claude` folder guard, file-state tracking, and
`/rewind` checkpointing. Model-independent by construction - a weaker model
on this station hits the same wall with the same steering.

Scope line, held deliberately: programs that write files at RUNTIME
(engines, installers, sqlite, builds) pass - the guard catches inline
content authoring only, so it routes without constricting. Quote-aware by
design via a single-pass shell quote STATE MACHINE (2026-07-12 hardening):
the shell view emits only characters that sit OUTSIDE quotes and are not
backslash-escaped, exactly mirroring how the shell tokenizes. So innocent
quoted text passes (`git commit -m "recall 73 > 90"`, `awk '{if ($1>5)…}'`,
`jq ".a > .b"` all write nothing and are not blocked), while a real redirect
between apostrophe-bearing quoted args (`echo "a'" > "b'"`) or behind escaped
quotes (`echo \"a > b\"`) is caught - both were false-negative bypasses under
the earlier blind `s/'…'//;s/"…"//` strip, which mis-parsed apostrophes as
quote openers and ignored `\`-escapes. Interpreter code (python `open()`,
node `writeFile`) is scanned in the RAW view because those writes legitimately
live inside quotes. Heredoc BODIES are stripped before the scan so a `>` in
heredoc DATA (`cat <<EOF | wc` … `5 > 3` … `EOF`) is not a false positive,
while a redirect on the heredoc command line (`cat > f <<EOF`) still denies.
Accepted adversarial-tier gaps (documented, not patterned): a write nested
entirely inside quotes (`bash -c 'echo x > f'`), `/dev/stdin` copies,
absolute-path `sed`, `ed`/`ex`, encode-decode chains, and (from the 2026-07-28
lane below) redirecting into the scratchpad then laundering the result to a
tracked path with an agent-planted `cp` or `ln -s` - the guard targets habit,
not containment. Harness-planted symlinks are a different matter and are
excluded structurally, not accepted; see the lane below. If
jq/perl are absent the hook fails open (both are §2 required deps). The state
machine is multiline-safe (perl -0777) so a multi-line quoted commit message
is one span, not N unquoted lines.

**Scratchpad lane (2026-07-28).** One sanctioned relaxation, scrubbed last in
the pipeline: a `>`/`>>`/`&>` whose target is a literal path inside THIS
session's scratchpad - `/tmp/claude-<uid>/<slug>/<session-id>/scratchpad/...`,
or `/private/tmp/...`, the macOS realpath - is removed from the shell view and
therefore passes. That one directory is disposable and sits outside every
repo, so a write there has no diff to review and no `/rewind` state to lose.
It was opened after measuring 45 real denials over sixteen days: redirect into
the scratch tree was the dominant surviving class, and each denial forced
program output back through the model's context, so the guard was inflating
the very context cost it was blamed for. Relaxed by DESTINATION, never by
purpose: an intent test ("program output, not authored content") is lexically
undecidable, since `python3 -c 'print("x")' > f` launders anything.

The anchor is the session's own `scratchpad/`, not the `/tmp/claude-<uid>/`
tree, and that distinction is load-bearing rather than cosmetic. The wider
tree is NOT disposable: the harness plants a sibling `tasks/` directory of
symlinks into `~/.claude/projects` (342 on this station, names like
`a732068d8cdeb8b81.output` that sit entirely inside any sane path charset), so
a tree-wide lane would have handed out truncate access to subagent transcripts
inside the folder `ask-before-claude-folder-edits.sh` exists to guard -
reachable by accident, not only by malice. The session-id anchor also stops
one session from clobbering a concurrently running session's working files,
which matters on a station that runs agents across projects at once. Both
holes were caught by the pre-merge security review of this very change; the
lesson generalizes - a path-scoped grant is only as good as an actual
inventory of what lives under the granted path.

The lane fails closed on every other axis: the target charset `[A-Za-z0-9._/-]`
excludes `$`, backticks, `~`, quotes and whitespace, so no expansion or command
substitution can hide in an allowed path; any `..` keeps the redirect
(traversal denies); a quoted target is already absent from the shell view and
denies; a wrong, glued or absent uid or session id denies; plain `/tmp/foo`
denies; a `(?<![<])` guard keeps `<>` read-write opens out of the lane so
check 1b still sees them. `tee`, in-place editors, `dd of=`, and interpreter
writes stay denied everywhere, scratchpad included - the lane is exactly one
operator family to exactly one directory. Deletion by the scrub cannot mask an
adjacent genuine write: the deleted span always ends immediately before a
terminator, and `>` is not in the terminator set, so a real `>` can never
become the first character after a deletion. Bulk edits over many files were
deliberately NOT unlocked: bulk is the worst case for unreviewed writes, not a
mitigating one, and the measured rate of genuine mass-edit attempts was two in
sixteen days. Accepted in the documented gap tier: redirect into the
scratchpad then `cp` the result to a tracked path, which is an overt second
command in the same visibility class as `bash -c 'echo x > f'`.
Table-driven tests live in the skills repo at
`tests/station-hooks/test-deny-bash-file-writes.sh` (99 cases: 54 deny, 42
pass, 3 structural); run after any edit to this script.

Script: [`claude-code/hooks/deny-bash-file-writes.sh`](claude-code/hooks/deny-bash-file-writes.sh).

### `agent-mail-check.sh`

SessionStart hook (matcher `startup|resume` - `clear` deliberately
excluded as the user's bypass, wired in §7): surfaces
unprocessed agent-mail for the current project at session boot. Deliberately
silent when the inbox is clean - zero output, zero context cost, no dry
fires. When top-level messages exist (excluding `processed/` and the HOW-TO
guide), it injects one compact line of model context (count + up to three
subjects) with `suppressOutput`, and the model relays it. Rationale: two
"Done" replies once sat unread for 12 days because the skill-level boot rule
depends on the model choosing to run it; a hook fires unconditionally.

Script: [`claude-code/hooks/agent-mail-check.sh`](claude-code/hooks/agent-mail-check.sh).

### `guard-rm.sh`

PreToolUse guard (matcher `Bash`, wired in §7): the delete-side companion to
`deny-bash-file-writes.sh`. Shell `rm` bypasses `/rewind` checkpointing and
diff review exactly as shell writes do, and a recursive `rm` of the wrong root
is unrecoverable. Two tiers. **DENY** (catastrophic, agent cannot self-approve):
a recursive `rm` targeting a filesystem/home root, the current or parent dir,
or `.git` - `rm -rf /`, `rm -rf ~`, `rm -rf $HOME`, `rm -rf .`, `rm -fr .git`,
including the `rm -rf / tmp` space-footgun and `sudo`/`$(…)`/brace-group
variants. **ASK** (real but plausibly legitimate, routed to the user with
steering toward `mv` into an `__archive/` folder): any recursive dir removal
(`rm -rf node_modules`), a glob delete (`rm *.log`), or a bulk delete fed by
`find -exec rm` / `xargs rm` (unbounded target set). Routine low-blast
removals - a single named file, no `-r`, no glob (`rm foo.txt`, `rm -f
stale.lock`) - **PASS**; the guard targets the dangerous habit, not every rm.

Quote-aware via the same shell state machine as its sibling, so `echo "rm -rf
/"` and a commit message mentioning `rm` are inert; the `rm` command word is
recognized after separators and after wrappers (`sudo`, `command`, `env`,
`xargs`, `time`, `nice`, find's `-exec`/`-execdir`), while `rm-stuff`,
`alarm`, and `npm run rm-foo` are not. Catastrophic detection defeats two
would-be evasions: a **quoted** doomsday target (`rm -rf "$HOME"`, `rm -rf
"/"`) is caught by scanning a quote-character-stripped view, and **path
arithmetic** that resolves to home/root (`rm -rf $HOME/../..`, `rm -rf
~/../..`, `rm -rf /var/..`) is caught by `normpath` resolution - which still
leaves a genuine subdir reached through `..` (`rm -rf $HOME/projects/../old`)
at ASK, not a false wipe. Accepted gaps (documented): `find -delete` and `git
clean -fdx` are not `rm` and are out of scope; a fully quoted command
(`bash -c 'rm -rf ~'`) is inert like its sibling's equivalent; relative
climbs without a trusted cwd resolve lexically only; if jq/perl are absent the
hook fails open, and if python3 is absent the climb check degrades to ASK
(both are §2 deps). Table-driven tests live at
`tests/station-hooks/test-guard-rm.sh` (48 cases: 24 deny, 11 ask, 11 pass, 2
structural); run after any edit.

Script: [`claude-code/hooks/guard-rm.sh`](claude-code/hooks/guard-rm.sh).

### `read-size-advisory.sh`

PreToolUse hook (matcher `Read`, wired in §7) - the **only non-blocking hook in
the set**. On a whole-file Read of a file over a byte threshold
(`READ_ADVISORY_BYTES`, default 200KB) it injects a one-line
`additionalContext` nudge: "big file - want it all? else use offset/limit or
`smart_outline`". A **targeted** read (offset/limit present) is silent - the
agent already knows what it wants. Every code path resolves to *allow*: it never
denies, never asks, never substitutes content. This is the deliberate,
constructive inverse of claude-mem's old blocking Read hook (§3.1) - it informs,
it does not withhold.

Design constraints, all load-bearing: **fail-open** (missing jq / unreadable
file / garbage payload → silent allow, never a block - enforced by the tests);
**cheap** (size from `stat`, O(1), never `wc -c` which reads the whole file -
this runs on every Read); **quiet by default** (200KB threshold set high on
purpose - a nudge that fires on ordinary files becomes noise and gets ignored,
so it must fire rarely to stay meaningful). Table-driven tests at
`tests/station-hooks/test-read-size-advisory.sh` (9 cases incl. the never-blocks
contract); run after any edit.

Script: [`claude-code/hooks/read-size-advisory.sh`](claude-code/hooks/read-size-advisory.sh).

### `memory-routing.sh`

PreToolUse hook (matcher `Write|Edit|MultiEdit|NotebookEdit|Update|Create`,
wired in §7) - GLOBAL (fires across every project). Advisory only, NEVER
blocks. When a **new** file is about to be created under a memory dir
(`~/.claude/projects/<slug>/memory/*.md`) it injects a routing table that asks
which category the belief is - (a) repo-specific → memory, (b) universal →
global CLAUDE.md, (c) invariant → a hook, (d) procedure → a skill, (e) client
fact → project docs, never memory. Only (a) proceeds. A yes/no "are you sure"
prompt failed to catch misfiles; naming the category is what exposes them.
Fires only on new files (an edit to an existing memory is already routed) and
uses the `permissionDecision:allow` + `additionalContext` channel so the note
reaches the agent without blocking. Fail-open. Tests:
`tests/station-hooks/test-memory-routing.sh` (7 cases incl. the never-blocks
contract).

Script: [`claude-code/hooks/memory-routing.sh`](claude-code/hooks/memory-routing.sh).

### `memory_lint.py`

PostToolUse hook (matcher `Write|Edit|MultiEdit|NotebookEdit|Update|Create`,
wired in §7) - GLOBAL. After a write to a memory file it lints that dir.
Deterministic violations **FAIL LOUD** (exit 2 - returns stderr to the agent so
it is fixed immediately): a memory file with no `MEMORY.md` pointer, a missing
index, missing/invalid frontmatter (`name`/`description`/`metadata.type` ∈
{user, feedback, project, reference}), a `name:` that does not match the
filename stem, or a dead index pointer. Judgment checks are advisory (stderr,
exit 0): dangling `[[wikilinks]]` (allowed - they mark a memory worth writing
later) and a doc-reconcile prompt. **Footgun (verified in `skill-authoring`):**
exit 2 returns stderr to the agent; exit 1 is swallowed - so fails use 2.
Stdlib only; **fails OPEN** (a bug in the lint exits 0, never blocks a write).
Tests: `tests/station-hooks/test-memory-lint.py` (12 cases).

Script: [`claude-code/hooks/memory_lint.py`](claude-code/hooks/memory_lint.py).

## 9. Status lines (`~/.claude/statusline.sh` + `subagent-statusline.sh`)

Two scripts, both wired up by §7's settings template, both requiring `jq`
(§2). Seed both verbatim.

### `statusline.sh` - main status line

Rendered on every prompt, two lines. **Line 1 - identity:** model, working dir
(basename of the workspace's current dir), git branch (hidden outside a repo,
short SHA on detached HEAD), and reasoning-effort level when reported.
**Line 2 - telemetry:** a context-usage bar that shifts green → yellow → red
at 70%/90% with used/window token counts, session cost, and session/weekly
rate-limit percentages (degrade to `--` when the API hasn't reported them
yet). Every segment is optional and drops out silently when its field is
absent.

![The main status line rendered: model, working directory and branch on line
one; context bar, cost and rate-limit percentages on line
two.](../images/statusline-expensive.png)

Script: [`claude-code/statusline.sh`](claude-code/statusline.sh).

### `subagent-statusline.sh` - running background tasks & subagents

One live row per background task / subagent in the agent panel (under the
main status line): status icon (● running / ◐ idle / ✓ done / ✗ error),
name, elapsed time, token usage with a ↑ trend arrow, and a truncated
description. This is the supported channel for live task/agent visibility -
the main statusLine JSON carries **no** task or subagent fields, so this
cannot be folded into `statusline.sh`.

Script: [`claude-code/subagent-statusline.sh`](claude-code/subagent-statusline.sh).

## 10. Keybindings (`~/.claude/keybindings.json`) + terminal setup

**Requirement:** on every station, **Shift+Enter inserts a newline** in the
chat prompt instead of submitting. Multi-line prompts are typed constantly;
a station where Shift+Enter submits mid-thought is misconfigured.

Two independent layers have to agree, and they fail differently:

1. **Claude Code's binding** - `~/.claude/keybindings.json` maps the key to
   an action. Portable, versionable, seeded from this spec.
2. **The terminal emulator** - it has to actually *send* a distinguishable
   Shift+Enter to the CLI. Some terminals do out of the box; some need
   `/terminal-setup`; some can't at all. Not seedable from here - it lives in
   the emulator's own config.

### 10.1 The file (seed verbatim)

The file is [`claude-code/keybindings.json`](claude-code/keybindings.json).

`/keybindings` in-session creates/opens this file; edits are picked up
without a restart. The action id is `chat:newline` (verified against
<https://code.claude.com/docs/en/keybindings> on 2026-07-13, Claude Code
2.1.208).

### 10.2 Terminal layer

- **Works with no setup:** Ghostty, kitty, iTerm2, WezTerm, Warp, Windows
  Terminal.
- **Needs `/terminal-setup` once:** VS Code, Cursor, Alacritty, Zed. The
  command writes to the *emulator's own* config, not to `~/.claude` - run it
  in the host terminal, **not** inside tmux/screen, which is why this layer
  is per-device and not seeded from this repo.
- **Cannot do it:** gnome-terminal, JetBrains terminals. Use the fallbacks.
- **tmux** also needs extended keys forwarded in `~/.tmux.conf`:
  ```
  set -g allow-passthrough on
  set -s extended-keys on
  set -as terminal-features 'xterm*:extkeys'
  ```
- **SSH** inherits the *local* emulator's behavior - the remote box's shell
  is irrelevant.

### 10.3 Fallbacks (always available, zero setup)

`Ctrl+J` and `\` followed by Enter both insert a newline in any terminal.
They are the answer on an unsupported emulator - do not chase a Shift+Enter
fix on gnome-terminal or a JetBrains terminal.

### 10.4 Verify

`~/.claude/keybindings.json` exists and parses (`jq . ~/.claude/keybindings.json`);
`claude --debug` reports no keybinding validation warnings; typing Shift+Enter
mid-prompt breaks the line instead of submitting. If the file is right but the
key still submits, the failure is layer 2 (terminal), not layer 1.

## 11. Bootstrap procedure (new device)

1. Install Claude Code; run it once so `~/.claude/` exists.
2. `brew install jq rtk-ai/tap/rtk` (plus git/gh/node/python3 if absent).
3. Clone the skills repo to `~/.agents` (ask the user for the remote), then
   `bash ~/.agents/sync-skills.sh`.
4. Seed `~/.claude/CLAUDE.md` (§5) and `~/.claude/RTK.md` (§6).
5. Create `~/.claude/hooks/` and seed all eight hook scripts (§8); seed
   `~/.claude/statusline.sh` and `~/.claude/subagent-statusline.sh` (§9).
6. Seed/merge `~/.claude/settings.json` (§7) - merge if one exists.
7. Seed `~/.claude/keybindings.json` (§10); if the terminal is one that needs
   it (VS Code, Cursor, Alacritty, Zed), run `/terminal-setup` once from the
   host terminal, outside tmux.
8. In Claude Code: `/plugin` → add the three marketplaces (§3) → install the
   four plugins. **Then seed `~/.claude-mem/settings.json` (§3.1)** so claude-mem
   does not intercept the Read tool - a default install blinds the agent from
   reading files. Restart the session.
9. **Verify:** `rtk gain` works; a Bash tool call shows rtk filtering; trying
   to `Read` a `.env` is denied with the stop-and-ask message; editing a file
   under `~/.claude` triggers the ask prompt; a whole-file `Read` of a file over
   200KB surfaces the size-advisory nudge (and still returns the file - it does
   NOT block); `claude-mem` does not summarize-in-place a `Read` (§3.1);
   `/mem-search test` (or `npx claude-mem search test`) answers; skills from
   `~/.agents/skills/` appear in the available-skills list; **Shift+Enter inserts
   a newline in the prompt instead of submitting** (§10.4).

## 12. What this spec deliberately leaves out

- **The repo remote URL and any account identity** - personal constants; ask
  the user (see the `no-hardcoded-personal-constants` house rule enforced by
  the `my-security-review-checklist` skill §8).
- **Device-local skills** - anything living only in one machine's `~/.claude`
  stays local by design; only `~/.agents` is canonical.
- **The terminal emulator's own config** - `/terminal-setup` writes into
  whatever emulator the device runs (§10.2); the emulator choice is per-device
  and its config file is not ours to seed. The spec states the *requirement*
  (Shift+Enter → newline) and the verify step; the emulator half is satisfied
  per machine.
- **claude-mem data** - observation history is per-user runtime state, not
  seedable config.

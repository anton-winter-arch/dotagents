# SPEC-CODEX.md - OpenAI Codex CLI station

The medium-stakes lane: everyday work that is not load-bearing. Config lives at
`~/.codex/`.

## Skills: nothing to install

Codex reads **`$HOME/.agents/skills`** directly. Cloning this repo to `~/.agents`
is the entire setup. It follows symlinked skill folders.

**Confirmed by observation 2026-07-31** on this machine.

Its full discovery set, per OpenAI's documentation on that date:

| Path | Scope |
|---|---|
| `$CWD/.agents/skills` | current directory |
| `$CWD/../.agents/skills` | parent, for nested repos |
| `$REPO_ROOT/.agents/skills` | repository root |
| `$HOME/.agents/skills` | user, and what this repo provides |
| `/etc/codex/skills` | system-wide |

Skills are invoked with `/skills` or by typing `$`, and Codex may also select one
implicitly from its description.

## What does not carry over

Only `skills/` is portable. **Confirmed by observation 2026-07-31: commands in
`~/.agents/commands/` do not appear in Codex**, while the skills beside them load.
Subagents are untested.

Codex has its own prompts and subagent mechanisms; this repo's `agents/` and
`commands/` trees target Claude Code. The portable path, if one is wanted, is
re-expressing them as skills carrying `disable-model-invocation: true` or
`context: fork` (backlog).

## Models

Codex runs OpenAI models, which are hosted third-party. Under `SPEC.md`
invariant 6 that bounds this station to **medium-stakes and hobby work**. Work
that matters runs on Anthropic or a genuinely local model, which means it does not
run here.

## Station config

Not yet adapted. `~/.codex/config.toml`, any hook or permission equivalents, and
an `AGENTS.md` template are a backlog item in `tasks/plan.md`. Codex uses
`AGENTS.md` where Claude Code uses `CLAUDE.md`.

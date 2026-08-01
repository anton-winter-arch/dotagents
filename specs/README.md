# specs/

One station spec per agent harness: what a machine's install of that harness needs
around these skills, and what it already provides on its own.

`SPEC.md` at the repo root says what this repo IS. These say what a *harness*
needs around it.

| Spec | Harness | Skills setup |
|---|---|---|
| [`SPEC-CLAUDE.md`](SPEC-CLAUDE.md) | Claude Code | `sync-skills.sh` |
| [`SPEC-CODEX.md`](SPEC-CODEX.md) | OpenAI Codex CLI | none, reads `~/.agents/skills` |
| [`SPEC-GOOSE.md`](SPEC-GOOSE.md) | goose | none, reads `~/.agents/skills` |
| [`SPEC-GEMINI.md`](SPEC-GEMINI.md) | Gemini CLI | none, reads `~/.agents/skills` |
| [`SPEC-KIMI.md`](SPEC-KIMI.md) | Kimi Code CLI | none, reads `~/.agents/skills` |
| [`SPEC-PI.md`](SPEC-PI.md) | Pi | none, reads `~/.agents/skills` |
| [`SPEC-DEEPAGENTS.md`](SPEC-DEEPAGENTS.md) | deepagents | passed in code |

Claude Code is the opinionated first choice and carries the fullest spec by a wide
margin: of the harnesses you install on a machine, it is the only one that needs a
setup step before it finds these skills, and its spec covers a whole station -
plugins, hooks, settings and permission rules - not just skills.
`SPEC-CLAUDE.md` records one opinionated setup rather than a neutral baseline: it
names specific plugins, hooks and permission rules, several of them third-party.
The plugins and their settings are optional - omit them and the rest still stands.

deepagents is the odd one out: a library rather than something you install on a
machine, so its spec covers wiring rather than a station. LangGraph sits under it
as the runtime and has no skills support of its own.

Of these, only Claude Code, Codex CLI and goose have been confirmed by direct
observation on a real machine. The rest are documentation-derived and each says so.

Every harness here except deepagents reads `~/.agents/skills/`. That is the whole
reason this repo lives at that path.

## Why most of these are short

Only one of the three trees in this repo is portable.

**`skills/` is a standard.** `~/.agents/skills/` is the cross-harness convention,
so a harness that reads it needs no install step and its spec has little to say
about skills.

**`agents/` is not.** Every harness names its own subagent directory, and Claude
Code's `~/.claude/agents/*.md` is not read by anything else. Gemini CLI's
`~/.gemini/agents/*.md` happens to use the same YAML-frontmatter-plus-prompt
shape, so those two are mechanically compatible even though neither reads the
other's path. Pi ships no subagents at all by design.

**`commands/` is not, and the formats differ.** Claude Code uses markdown at
`~/.claude/commands/*.md`; Gemini CLI uses **TOML** at `~/.gemini/commands/*.toml`.
These are different artifacts, not one artifact at two paths. Confirmed by
observation on 2026-07-31: commands in `~/.agents/commands/` appear in neither
Codex nor goose, while the skills beside them load.

The standard's own answer to both is to fold them into skills:
`disable-model-invocation: true` makes a skill behave as an explicit slash
command, and `context: fork` runs one in an isolated subagent. Each spec should
say which of those its harness honors, because that is the portable path.

A spec here is long-lived and describes current state. Session records and retired
per-feature specs live in `tasks/completed/`.

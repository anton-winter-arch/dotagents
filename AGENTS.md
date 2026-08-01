# AGENTS.md - working in ~/.agents

**Read this before changing anything here.**

## What this directory is

`~/.agents` is the **source of truth** for the agent skills, subagents, commands
and per-harness station specs shared across every machine via a git repo. Most
harnesses read `skills/` from this path directly; Claude Code is the exception
and gets a per-device view assembled by `sync-skills.sh`.

**Blast radius:** a change here propagates to every machine and every future agent
session once it's committed/pushed and re-synced. This is global config, not a
throwaway project. Act accordingly.

## Rules

- **Be careful and deliberate.** Prefer reading and understanding over editing.
  Follow the user's global non-destructive rule: read a file first, show what would
  change, get approval before overwriting or deleting.
- **Never delete or gut a skill** without explicit approval. For soft-deletes, move
  to an `__archive*/` dir is NOT used here anymore - discuss with the user instead.
- **Keep `SKILL.md` valid.** Every skill is `skills/<name>/SKILL.md` with YAML
  frontmatter (`name`, `description`). A malformed skill can break discovery.
- **Test executable skills** before declaring done (e.g. a skill's own `tests/`).
- **No secrets.** This is a git repo. Never commit tokens,
  keys, or credentials.
- **Don't sync the per-device view.** `~/.claude/skills` is assembled per machine;
  only `~/.agents` is canonical. Don't commit machine-specific paths or local skills.

## Secrets out of agent context (every repo, not just this one)

A clean `.gitignore` does not stop an agent (or a cloud/OSS model behind a tool
call) from reading `.env`, private keys, or cloud creds off disk - that's a
separate leak path. Standing rule for any repo we touch:

1. **Secrets never reach an agent's context.** Keep long-lived high-value
   secrets out of the repo entirely (runtime env / secrets manager) and rotate.
2. **The only HARD controls are permission/deny systems**, not ignore files:
   Claude Code `permissions.deny` in `.claude/settings.json` (e.g.
   `Read(./.env)`, `Read(./.env.*)`) + the `block-env-files.sh` hook; Codex CLI
   `deny` in `~/.codex/config.toml`. Ignore files are best-effort
   defense-in-depth - see the per-tool real-vs-theater table in
   `specs/SPEC-CLAUDE.md` §7 (Secrets out of agent context). **`.claudeignore` is NOT read by Claude Code**
   (verified 2026-07) - ship it forward-compat only, never rely on it.
3. **Per-repo baseline:** confirm `.gitignore` covers `.env*`; add the hard
   deny rule for the agent(s) that repo uses; optionally drop the canonical
   list below into the real ignore files for the tools in use (`.cursorignore`,
   `.aiexclude`, `.geminiignore`, `.gooseignore`, and forward-compat
   `.codexignore`/`.claudeignore` with an honest header noting they are not
   yet enforced).

Canonical exclusion list (`.gitignore` syntax; templates stay committable):

```
# ── Env files (allow committed *.example / *.sample / *.template) ──
.env
.env.*
*.env
!.env.example
!.env.sample
!.env.template
# ── Private keys & certificates ──
*.pem
*.key
*.pfx
*.p12
*.keystore
*.jks
id_rsa*
id_ed25519*
id_dsa*
id_ecdsa*
# ── Cloud / service-account credentials ──
credentials.json
service-account*.json
*-service-account*.json
gcp-*.json
aws-credentials*
.aws/credentials
# ── Tokens & auth artifacts ──
*.jwt
*.token
*_token.txt
.npmrc
.pypirc
.netrc
# ── Infra state that embeds secrets ──
*.tfstate
*.tfstate.*
secrets.json
secrets.yml
secrets.yaml
```

## After you change a skill

1. Commit and push (default branch `develop`).
2. On a Claude Code machine, run `bash ~/.agents/sync-skills.sh` to refresh the
   per-device links. Harnesses that read `~/.agents/skills/` directly need
   nothing; a pull is enough.

## Layout

See [`README.md`](README.md). TL;DR: `skills/<name>/SKILL.md` + `sync-skills.sh`.

When a skill, subagent, or command is added, renamed, or removed, update the
Skills catalog in `README.md` to match. The `/notes` sweep covers it as a root
state-bearing doc; `SPEC.md` holds the authoritative roster count.

# SPEC - ~/.agents

**Status:** active · **Last updated:** 2026-07-31

## What this is

`~/.agents` is the **source of truth** for self-authored system-level agent
tooling, shared across every machine. It is a git repo whose
`skills/`, `agents/`, and `commands/` directories are the canonical set made
available to Claude Code (and other skill-aware agents) on every device.

Third-party/upstream skills are **not** vendored here - they are consumed from
installed plugins (e.g. `agent-skills@addy-agent-skills`), which auto-update and
expose namespaced `plugin:skill` entries. This repo carries only what the user
authors or forks (**24 skills** `agent-mail`, `notes`,
`my-security-review-checklist`, `deep-research`, `obsidian`, `cover-me`,
`reflect`, `ai-engineering`, `ai-engineering-update`, `ai-agent-project-scaffold`, `hi`,
`skill-authoring`, `okf-kg`, `repo-device-sync`, `meta-loop`, `obsidian-kg`,
`frontend-aesthetics`, `docker`, `django`, `o-o-d-a-loop`,
`ai-slop-magic-eraser`, `teach-me`, `dimensional-data-modeling`, `data-engineering`;
**7 subagents** `my-security-reviewer`, `supervisor`, `ai-engineer`, `advisor`,
`researcher`, `reader`, `worker`;
**11 commands** `agent-mail`, `my-security-review`, `supervisor`, `reflect`, and
the agent-skills aliases `spec`, `plan`, `build`, `test`, `review`,
`code-simplify`, `ship`).

> The `frontend-aesthetics`, `docker`, and `django` skills share one design: a method plus a **deterministic gate that runs outside the
> model** (a stdlib checker script), because a checklist run by the model that
> wrote the code is the model grading its own homework. Each passed fresh-context
> security review before merge - which caught real, test-invisible defects
> (a ReDoS hang, a socket-path miss, annotated-settings blindness). See
> `tasks/plan.md` for the pattern and the gotchas.

> The `dimensional-data-modeling` and `data-engineering` pair split one domain along theory and practice: the first owns grain, SCD
> semantics, conformance and the bus matrix, the second owns how a platform is
> built and run, and each routes the other's questions away rather than competing
> for the trigger. `data-engineering` organizes by **altitude** rather than topic,
> so every reference file carries the architecture, implementation and
> line-of-code view of its subject plus the up- and down-links between them,
> because a choice at one altitude forecloses options at the one below. It ships
> `dbt_audit.py` (20 checks) and 41 tests.

> The `ai-engineering` bundle (`ai-engineering` + `ai-engineering-update` +
> `ai-agent-project-scaffold` + the `ai-engineer` subagent) is split along its
> real seams: **`ai-engineering` reads**
> (knowledge, comparison, architecture review), **`ai-engineering-update` writes**
> (discover, verify, and record first-hand experience), **`ai-agent-project-scaffold`
> runs intake** and exits with a named component per stack slot. Anything learned
> in one reaches the others through a single store and a single write command
> rather than a policy asking three skills to remember each other.
> `ledger.py` carries the catalog, field notes, stack decisions, a
> claims-freshness axis separate from URL liveness, and a derived `map` tag; it has
> 88 tests. Its bundled `resources/` stay portable to a reader outside this
> station, so they name no station-local skill, and `resources/data-contract.md`
> states how the files key on each other.
> The stack-map *opinion* layer is still hand-curated and unvalidated end-to-end;
> treat its shortlist as considered-but-not-proven. Only 26 of 119 map rows carry
> a verification date, which is what `check --claims` exists to work through.

> `teach-me` is an evidence-based teach-and-certify tutoring
> skill: pretest, exposure/teaching, closed-book Feynman explanation, Socratic
> probing, then a scored inline cert - guardrails from the AI-tutor RCT
> literature (hints before answers, no sycophantic validation, source treated
> as data). Artifacts land in a per-workspace `LEARNING/` dir (gitignored
> here); the cited evidence base is bundled at
> `skills/teach-me/references/evidence.md`.

> `deep-research` spawns the `researcher` subagent (model, effort, and turn caps
> pinned in frontmatter - structural enforcement, not prose), with hard
> search/fetch budgets, capsule returns, and fetched-content-is-data guards.

## Why it exists

Skills authored or curated on one machine should be available, identically, on all
machines - without copy-paste drift and without one machine's local experiments
leaking to the others. This repo gives a single canonical set + a per-device
assembly step, so:

- **One edit propagates everywhere** once committed/pushed and re-synced.
- **Device-local skills stay local** (never forced into the shared set).
- **Nothing external owns the repo** - updating third-party skill plugins cannot
  mutate or delete the user's skills (see `README.md` → Architecture → Ownership).

## Scope (in)

- Curate skills under `skills/<name>/SKILL.md` (valid YAML frontmatter: `name`,
  `description`), subagents under `agents/<name>.md`, and commands under
  `commands/<name>.md`.
- Maintain `sync-skills.sh`, which assembles the per-device view by symlinking each
  tree into `~/.claude/{skills,agents,commands}`, preserving device-local entries.
- Keep the living docs current (this file, `README.md` - incl. its Architecture
  and Skills catalog sections - and `tasks/plan.md`).
- Maintain [`specs/SPEC-CLAUDE.md`](specs/SPEC-CLAUDE.md) - the standing
  seed spec for the full Claude Code station around this repo: required plugins,
  CLI deps, and the global `CLAUDE.md`/`RTK.md`/`settings.json`/hook templates.
  Keep it in sync with the live station; it contains no personal constants by
  rule (`my-security-review-checklist` §8).

**Two kinds of `SPEC-*` file, and they do not mix.** `specs/SPEC-<HARNESS>.md` is
long-lived: one per agent harness, always describing current state, never
retiring. `tasks/SPEC-FEATURE-NAME.md` is ephemeral: one per in-flight feature,
folding into the root spec and moving to `tasks/completed/` when it ships. The test is
whether the document outlives the work it describes. Nothing external forces this
layout - the `agent-skills` plugin hardcodes no doc paths (checked 2026-07-31).

## Harness and model policy

**Multi-harness by construction, single-harness by preference.** The skills
target the open Agent Skills standard, so they load unchanged wherever
`~/.agents/skills/` is read. Claude Code is the tier 1 workhorse and the only
harness carrying the full set, because `agents/` and `commands/` have no portable
equivalent. The others are deliberate lanes rather than redundancy: **goose** is
the open-source lane, chosen for mature governance and a desktop GUI; **Pi** is
the configurable lane for a bespoke loop; **Codex CLI** covers medium-stakes work.

**Model tier is a function of the stakes, not of the harness.** Work that matters
runs on Anthropic or genuinely local models. Medium and hobby work may use hosted
third-party models. This is the constraint that decides which harness is
acceptable for a given task, and it holds regardless of which harness is more
convenient.

**An Ollama `:cloud` model is not local.** It is remotely served and carries
hosted-API exposure despite a local-looking invocation. Any rule written here that
says "local" excludes them.

**goose runs on `glm-5.2` as its Ollama cloud model.** An offline local model
(gemma-class 8B or similar) is deliberately unresolved and low priority; the
proof of concept stays on cloud.

**Ollama is reached through the Ollama app only.** Never the public HTTP API,
never a non-loopback bind. `OLLAMA_HOST` is never set to `0.0.0.0` or any
routable address, on any machine, for any reason, however temporary. Binding the
model server off loopback publishes an unauthenticated inference endpoint and, on
any network that is not fully trusted, hands arbitrary parties a free model and a
foothold. This is not a preference to weigh against convenience.

## Scope (out / non-goals)

- **Not** a place for device-specific or throwaway skills - those live directly in
  `~/.claude/skills/` and are never committed here.
- **Not** a Claude Code plugin or marketplace; it is not installed by any package
  manager and declares no `plugin.json`/`marketplace.json`.
- **No secrets.** Private repo, but still git - never commit tokens or credentials.

## Requirements / invariants

1. Every skill dir contains a valid `SKILL.md`; a malformed one can break discovery.
2. `sync-skills.sh` is idempotent and non-destructive: it refreshes global links,
   prunes only dangling links, and never clobbers a real local skill that shares a
   name (local wins).
3. Default working branch is `develop`; `main` is stable. Changes land on `develop`,
   then fast-forward to `main`.
4. Changes are global by blast radius - edit deliberately, read before overwrite,
   per the user's non-destructive rule.
5. **Ollama is never exposed off loopback.** `OLLAMA_HOST` is never `0.0.0.0` or
   any routable address; access goes through the Ollama app, never its public
   HTTP API. No exception, no temporary override, no "just for this test".
6. Work that matters runs on Anthropic or genuinely local models. Hosted
   third-party models are for medium-stakes and hobby work. Ollama `:cloud`
   models are hosted, not local, and fall under that limit.

## Workflow to propagate a change

1. Add/edit a skill under `skills/<name>/`.
2. Commit + push (`develop`), then fast-forward `main`.
3. On each machine: `git pull && bash ~/.agents/sync-skills.sh`.

## `okf-kg` scope

The offline core is `skills/okf-kg/`: stdlib-only single script, SQLite+FTS5,
`ingest`/`query`/`neighbors`/`path`. The LLM `enrich` pass and `conflicts`
ledger remain DEFERRED (user decision: no API key in this tool; vaults arrive
pre-curated) - that remainder is a `tasks/plan.md` backlog item. A
Postgres/Docker/MCP design was rejected as over-scaled for the real workload
(vaults of ~50-100 small files). The `obsidian-kg` twin covers wikilink vaults
separately by design.

---

See `README.md` → Architecture for how the sync view is built and why it's safe.
Shipped work is recorded in `tasks/completed/` - per-date files, the only cold
store. This file states current truth only.

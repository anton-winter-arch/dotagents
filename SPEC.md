# SPEC - ~/.agents

**Status:** active · **Last updated:** 2026-07-28

## What this is

`~/.agents` is the **source of truth** for the user's **own** system-level agent
tooling shared across all the user's machines. It is a private git repo whose
`skills/`, `agents/`, and `commands/` directories are the canonical set made
available to Claude Code (and other skill-aware agents) on every device.

Third-party/upstream skills are **not** vendored here - they are consumed from
installed plugins (e.g. `agent-skills@addy-agent-skills`), which auto-update and
expose namespaced `plugin:skill` entries. This repo carries only what the user
authors or forks (as of 2026-07-28: **22 skills** `agent-mail`, `notes`,
`my-security-review-checklist`, `deep-research`, `obsidian`, `cover-me`,
`reflect`, `ai-engineering`, `ai-engineering-update`, `ai-agent-project-scaffold`, `hi`,
`skill-authoring`, `okf-kg`, `repo-device-sync`, `meta-loop`, `obsidian-kg`,
`frontend-aesthetics`, `docker`, `django`, `o-o-d-a-loop`,
`ai-slop-magic-eraser`, `teach-me`;
**5 subagents** `my-security-reviewer`, `supervisor`, `ai-engineer`, `advisor`,
`researcher`;
**11 commands** `agent-mail`, `my-security-review`, `supervisor`, `reflect`, and
the agent-skills aliases `spec`, `plan`, `build`, `test`, `review`,
`code-simplify`, `ship`).

> The `frontend-aesthetics`, `docker`, and `django` skills (added 2026-07-14)
> share one design: a method plus a **deterministic gate that runs outside the
> model** (a stdlib checker script), because a checklist run by the model that
> wrote the code is the model grading its own homework. Each passed fresh-context
> security review before merge - which caught real, test-invisible defects
> (a ReDoS hang, a socket-path miss, annotated-settings blindness). See
> `tasks/plan.md` for the pattern and the gotchas.

> The `ai-engineering` bundle (`ai-engineering` + `ai-engineering-update` +
> `ai-agent-project-scaffold` + the `ai-engineer` subagent) landed 2026-06-30/07-01
> and was split along its real seams on 2026-07-27: **`ai-engineering` reads**
> (knowledge, comparison, architecture review), **`ai-engineering-update` writes**
> (discover, verify, and record first-hand experience), **`ai-agent-project-scaffold`
> runs intake** and exits with a named component per stack slot. Anything learned
> in one reaches the others through a single store and a single write command
> rather than a policy asking three skills to remember each other.
> `ledger.py` carries the catalog (506 rows), field notes, stack decisions, a
> claims-freshness axis separate from URL liveness, and a derived `map` tag; it has
> 88 tests. Its bundled `resources/` stay portable to a reader outside this
> station, so they name no station-local skill, and `resources/data-contract.md`
> states how the files key on each other.
> The stack-map *opinion* layer is still hand-curated and unvalidated end-to-end;
> treat its shortlist as considered-but-not-proven. Only 26 of 119 map rows carry
> a verification date, which is what `check --claims` exists to work through.

> `teach-me` (added 2026-07-28) is an evidence-based teach-and-certify tutoring
> skill: pretest, exposure/teaching, closed-book Feynman explanation, Socratic
> probing, then a scored inline cert - guardrails from the AI-tutor RCT
> literature (hints before answers, no sycophantic validation, source treated
> as data). Artifacts land in a per-workspace `LEARNING/` dir (gitignored
> here); the cited evidence base is bundled at
> `skills/teach-me/references/evidence.md`; the shipped spec is archived at
> `tasks/completed/SPEC-TEACH-ME-2026-07-28.md`. The same session hardened
> `deep-research`: it now spawns the `researcher` subagent (model, effort, and
> turn caps pinned in frontmatter - structural enforcement, not prose), with
> hard search/fetch budgets, capsule returns, and fetched-content-is-data
> guards.

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
- Maintain [`SPEC-CLAUDE.md`](SPEC-CLAUDE.md) (added 2026-07-03) - the standing
  seed spec for the full Claude Code station around this repo: required plugins,
  CLI deps, and the global `CLAUDE.md`/`RTK.md`/`settings.json`/hook templates.
  Keep it in sync with the live station; it contains no personal constants by
  rule (`my-security-review-checklist` §8).

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

## Workflow to propagate a change

1. Add/edit a skill under `skills/<name>/`.
2. Commit + push (`develop`), then fast-forward `main`.
3. On each machine: `git pull && bash ~/.agents/sync-skills.sh`.

## Shipped - `okf-kg` (core shipped 2026-07-03; spec archived 2026-07-10)

The offline core shipped as `skills/okf-kg/`: stdlib-only single script,
SQLite+FTS5, `ingest`/`query`/`neighbors`/`path`. The LLM `enrich` pass and
`conflicts` ledger remain DEFERRED (user decision: no API key in this tool;
vaults arrive pre-curated) - that remainder is a `tasks/plan.md` backlog item; the
full spec text is archived in `tasks/completed/` (folded
SPEC-COMPLETED section; root `SPEC-OKF-GRAPH.md` retired). History: the earlier Postgres/Docker/MCP draft
was removed 2026-07-02 as over-scaled for the real workload (vaults of
~50-100 small files). The 2026-07-09 `obsidian-kg` twin covers wikilink
vaults separately by design.

---

See `README.md` → Architecture for how the sync view is built and why it's safe.
Shipped work is recorded in `tasks/completed/` - per-date files, the only cold
store (SPEC-COMPLETED.md retired 2026-07-13; the single `plan-completed.md` append
log was split into per-date files 2026-07-26; this file states current truth only).

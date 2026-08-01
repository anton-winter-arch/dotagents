---
name: notes
description: End-of-session documentation sweep. Use when the user types /notes, says "take notes", "update the docs", "write up the session", or at the end of ANY work session - including in a fresh repo with no docs yet - to capture everything completed, learned, resolved, decided, planned, implemented, or discovered into the repo's living docs (SPEC.md, README.md, tasks/plan.md, tasks/todo.md, created if missing), enforce the hot-file size budgets, and roll finished work into tasks/completed/, the per-date cold-storage folder.
---

# Notes - session documentation sweep

A ping to stop and write down what this session actually produced, then fold it
into the repo's living documentation so the next session (yours or another
agent's) starts from current truth instead of stale files.

Run this when invoked as `/notes`, when the user asks to "take notes" / "update
the docs" / "write up the session", or proactively when wrapping up substantive
work.

## Step 1 - Reconstruct the session

Before touching any file, think back over the whole session and list, concretely:

- **Completed** - what got built, fixed, or shipped (with file paths).
- **Learned / discovered** - non-obvious facts about the codebase, tools, or
  environment that weren't written down anywhere.
- **Resolved** - bugs, blockers, or questions that are now answered.
- **Decided** - choices made and the *why* (the reasoning, not just the outcome).
- **Planned** - next steps, follow-ups, and known-but-deferred work.
- **Implemented / changed** - architecture or interface evolution.

Pull from the actual conversation and the working tree. Cross-check with
`git status` and `git diff` / `git log` so nothing real is missed and nothing
imagined is added. **Validate before writing - do not invent progress.**

## Step 2 - Locate the docs

These live at the **repo root** (not under `.claude/`). Check which exist:

| File | Role |
|------|------|
| `README.md` | The USE guide, for a reader who is not you: what it is, how to run it, how to use what it ships. Roster level - name the parts, link to their own files, don't restate how each works. Rationale, gotchas, internals and status go to `tasks/plan.md`. Carve-out: an architecture section belongs here when the mechanism IS what the reader operates (a sync model, a protocol, a data flow), never as a standalone file |
| `SPEC.md` | The ARCHITECTURAL spec, for whoever maintains or extends it: what it is, what it deliberately is not, invariants, boundaries, constraining decisions. Always true to now; completed history does NOT accumulate here. README says how to USE it; SPEC says what it IS |
| `tasks/plan.md` | Active plan + backlog (tasks with acceptance criteria + verification) AND dev docs (design decisions, gotchas, failure modes) (hot) |
| `tasks/completed/` | THE cold store - a folder of `plan-completed-YYYY-MM-DD.md` files (one per working day, append-only on that day, immutable after) plus retired feature specs moved in as whole files. The ONLY dated archive; no root-level `*-COMPLETED.md` files and no single infinite append log. A repo's own externally-conventioned `log.md`/changelog (where one exists) stays separate |
| `tasks/todo.md` | Session-to-session handoff snapshot - goes stale fastest; refresh or absorb per its own header |
| `tasks/SPEC-FEATURE-NAME.md` | Ephemeral per-feature spec (hot, in the `tasks/` bundle) - one per in-flight feature. On completion its durable details fold into root `SPEC.md` and the file MOVES to `tasks/completed/SPEC-FEATURE-NAME-YYYY-MM-DD.md`; it is NOT a living doc |

**How the `tasks/` folder works** - it is the self-contained *working bundle* for
the active increment, distinct from the durable root docs (`SPEC.md`/`README.md`):

- `tasks/plan.md` - the plan + living dev docs. Always present, hot.
- `tasks/todo.md` - next actions + session handoff. Always present, hot.
- `tasks/SPEC-FEATURE-NAME.md` - an **ephemeral** per-feature spec that joins the
  bundle only while that feature is in flight; one file per feature, named for it.
- `tasks/completed/` - **THE** cold store. Finished plan items, closed dev
  notes, and shipped-spec records land in `plan-completed-YYYY-MM-DD.md` (one
  file per working day, headed `## YYYY-MM-DD`); retired feature specs move in
  as whole files with a ship-date suffix. Only today's file is ever written;
  past dates are immutable.

Flow: plan the work in `plan.md` (+ a `SPEC-FEATURE-NAME.md` when it's a feature),
track it in `todo.md`; on completion, rewrite the durable truth into the root
`SPEC.md`, then **move** the finished records into `tasks/completed/` - the
day's records into today's `plan-completed-YYYY-MM-DD.md`, the retired
`SPEC-FEATURE-NAME.md` as its own dated file (a real `git mv`, never a paste).
Hot files stay lean and current; nothing is deleted, only relocated.

Also scan any other root `*.md` asserting current state - secondary specs
(`SPEC-*.md`), `AGENTS.md`, rules files - for claims the session invalidated.
A shipped secondary spec's material rolls into `tasks/completed/` like any
other finished work (`SPEC-COMPLETED.md` is retired, 2026-07-11 standard -
fold one into `tasks/completed/` if a repo still carries it).

Not every repo has all of them. **Read each file that exists before editing it.**
For a hot file that's missing but clearly warranted by the work, create it. Do
**not** fabricate a `*-COMPLETED.md` file unless there's finished work to move
into it.

> **Legacy layouts:** a repo may still carry (a) a single
> `tasks/plan-completed.md` append log (pre-2026-07-26 convention) - convert it
> on this sweep: split by its `## YYYY-MM-DD` headers into
> `tasks/completed/plan-completed-YYYY-MM-DD.md`, verbatim, then remove the
> original; or (b) root `PLAN.md` / `PLAN-COMPLETED.md` / `HANDOFF.md` (the
> 2026-07-03→07-10 interlude) - sweep into those where they exist and suggest
> converting to `tasks/plan.md` + `tasks/todo.md` (cold: `tasks/completed/`)
> rather than mixing layouts. That layout is a house convention, not an external
> requirement: the `agent-skills` plugin hardcodes no doc paths at all (checked
> 2026-07-31), so nothing upstream constrains it.

## Step 3 - Size gate (mandatory, before writing anything)

Measure every hot file that exists before adding a word:

```bash
wc -l SPEC.md README.md tasks/plan.md tasks/todo.md
```

House budgets (a repo may state its own in the file header; otherwise these):

| File | Budget | Rule when over |
|------|--------|----------------|
| `tasks/todo.md` | ~100 lines | It is a snapshot, not a log: absorb and rewrite per its own header. Threads resolved this session leave; surviving threads compress to state + next action + pointer. |
| `tasks/plan.md` | ~400 lines | Active plan + current dev docs only. Shipped narrative, superseded decisions, and closed gotchas move to cold storage (Step 5). |
| `SPEC.md` / `README.md` | skimmable | Rewrite stale sections in place; history never accumulates here. |

Over budget means this sweep **includes a reduction pass, not just additions**.
Appending the session's record while leaving everything already there is the
failure mode this gate exists to stop - a hot file that only ever grows is a
dumping ground, and every session after it pays the context cost.

Reduction rules:
- **Finished or superseded content** relocates to cold storage - always
  sanctioned, that is the lifecycle working as designed.
- **Live but verbose entries** compress per "Writing hot-file entries" below:
  state, blocker, next action, pointer to the full record.
- **Unresolved items are never dropped.** If a thread's liveness is unclear,
  keep a one-line pointer and flag it in the report for the user to rule on.
- Compression of substantial content the user authored by hand is proposed in
  the report, not applied silently; mechanical trims of agent-written entries
  are applied directly.

## Step 4 - Update hot files

For each hot file (`SPEC.md`, `README.md`, `tasks/plan.md`, `tasks/todo.md`):

- Merge the session findings in - refresh stale statements, add what's new,
  correct what's wrong. Edit surgically; preserve the file's existing voice,
  structure, and unrelated content.
- Keep hot files **lean and current**: they describe the *active* state, not
  history. Mark finished tasks done, then move them out in Step 4.
- Record decisions with their rationale (the *why*), and note new gotchas /
  failure modes in `tasks/plan.md`'s dev-docs sections.

### Writing hot-file entries

These files load into context every session. **A hot file is a working index,
not a narrative.**

- **One entry, a few lines.** State, blocker, next action, pointer to the full
  record. Longer than a short paragraph means the detail belongs in
  `tasks/plan.md` or the cold store.
- **Point, do not restate.** A second copy of what cold storage already holds is
  free to drift.
- **Mandatory detail only.** Exact names, paths, commands, blockers, decisions
  and their one-line why.
- **Cut** narration of how the work went, replayed debate, rejected options,
  hedging, and superseded history kept "for context".
- **Nested bullets under a heading**, never a paragraph of bolded clauses.

**Concision is not the goal. Information density is.** A one-line entry that
omits the blocker is as broken as a paragraph that retells the week:

> 9. **BLOCKED - read access to the reporting DB.** Requested 2026-03-01,
>    ticket OPS-4412, no owner assigned. Blocks items 10 and 14.
>    **Escalate if not granted by 03-08.**

`references/hot-file-entries.md` has an example per entry type (shipped
initiative, active workstream, blocker, decision, handoff, correction) plus a
routing table for what belongs in which file. Read it before writing entries.

## Step 5 - Roll completed work into cold storage

Lifecycle: finished work leaves the hot file and lands in `tasks/completed/`,
in **today's** file only. **Relocate, never delete.**

- Completed `tasks/plan.md` items and closed dev notes → append to
  `tasks/completed/plan-completed-YYYY-MM-DD.md` (today's date from the
  environment / `date +%F`; don't guess), headed `## YYYY-MM-DD`. Create it on
  first use; create `tasks/completed/` (with a short README) if the repo
  doesn't have it yet.
- Shipped-spec material → `SPEC.md` is rewritten to current state (it never
  accumulates history) and the shipped record lands in today's
  plan-completed file with the rest of the finished work.
- Shipped `tasks/SPEC-FEATURE-NAME.md` per-feature spec → its durable details
  are rewritten into the root `SPEC.md`, then the file itself MOVES:
  `git mv tasks/SPEC-FEATURE-NAME.md tasks/completed/SPEC-FEATURE-NAME-YYYY-MM-DD.md`.
  Never paste a spec's body into the log; the move preserves it as a file.

Past-date files in `tasks/completed/` are immutable - never edit or append to
a previous day's file; corrections happen in the living docs.

## Step 6 - Re-measure and report (mandatory close)

Re-run the Step 3 measurement on every hot file touched and report
**before → after line counts**. A hot file may end larger than it started only
when the session genuinely added that much *active* state - and the report must
say so in one line. Ending over budget without naming what should move, and
who decides, fails the sweep.

Then summarize what changed: which files were updated or created, what moved to
cold storage, and anything deliberately left out (e.g. nothing finished enough
to archive yet). If a doc wants a bigger restructure than this sweep should make
unilaterally, flag it rather than doing it.

## Guardrails

- **Non-destructive.** Read before edit; never overwrite or gut a file's content
  to "rewrite" it - merge. Show/keep what was there. Relocation to cold storage
  is not deletion; it is the only sanctioned way hot files shrink.
- **Appending is not maintaining.** Every sweep runs the Step 3 size gate and
  the Step 6 re-measure; a notes pass that only adds is incomplete.
- **Don't name the user** anywhere in the docs.
- **Evidence over narrative.** Every claimed accomplishment should trace to a real
  change in the tree or conversation.
- This skill writes docs only. It does not commit or push unless the user asks.

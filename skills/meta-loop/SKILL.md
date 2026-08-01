---
name: meta-loop
description: Orchestration loop - plan, delegate to parallel workers, verify, synthesize - with a premium advisor consulted off the hot path. The session model orchestrates, workers run as Agent calls on model opus by default (dropping to sonnet only for genuinely low-stakes subtasks), and the advisor agent (model fable) is pulled in for decomposition critique, risk, and taste. MUST be used whenever the user asks to run something as a loop, orchestrate, fan out, or delegate to workers ("run this as a meta loop", "orchestrate this", "fan this out with an advisor", "use cheap workers for the leg work"), whenever a requested task visibly splits into three or more independent subtasks, and for any mid-loop situation: verifying a worker's returned result against its claims, re-delegating a rejected subtask, or critiquing a decomposition before fan-out. Also on "/meta-loop". Not for single-file or single-step tasks.
---

# meta-loop

Three-tier loop: **orchestrator** (this session) runs the hot path
plan → delegate → verify → synthesize; **workers** (opus) do parallel
execution; **advisor** (fable, fresh context) is a consulted advisor off the
hot path. The economics: parallelism is the leverage, not a cheaper worker. A
worker runs on the same tier the orchestrator would have used doing the work
itself, so fanning out costs wall-clock and context - never quality. The saving
is structural rather than per-token: no single agent fills a context window, so
several shorter threads cost less in aggregate than one long thread that maxes
out and compacts repeatedly.

Session-model note: a skill cannot set the main-thread model. Run the session
on Opus (`/model opus`) so the orchestrator matches its workers; on a Fable
session the loop still works - the advisor then buys a fresh, unanchored
context rather than a model upgrade. Worker tier does not follow the session:
`model: "opus"` is passed explicitly on every `Agent` call, because an
omitted `model` inherits the session model and a cheap session would silently
downgrade the whole fan-out.

## Phase 1 - Plan (orchestrator)

Write the plan before spawning anything: subtasks, each with a concrete
deliverable and acceptance criteria the orchestrator can check from evidence
(diff, test output, file list - not the worker's own say-so). Mark which
subtasks are independent (parallel) and which chain. If fewer than ~3
independent subtasks fall out, stop - do the work directly; the loop is
overhead, not leverage.

## Phase 2 - Advisor consult (on demand, pre-delegation)

Spawn the `advisor` agent with the plan and one specific question
(default: "critique this decomposition - seams, ordering, risk").
Apply the verdict - proceed / revise / stop - before any worker starts.

**The advisor is available, and it is the expensive tier.** It runs on
`fable`, the priciest model in the loop; it is a scalpel, not a habit.

- **Consult when:** subtasks touch shared files or a common interface; any
  step is irreversible (migrations, deletions, published output); the
  decomposition itself is uncertain and a wrong split would waste the whole
  fan-out; the user asked for it. When one of those holds, do not skip it to
  save tokens - that is exactly the call the advisor pays for.
- **Skip when:** the fan-out is routine, the seams are obvious, and a bad
  plan would be cheap to redo. Most loops need zero or one consult.
- **Budget:** typically 0–2 advisor calls per loop - one at plan time, at
  most one taste/escalation pass later. Never one advisor call per subtask,
  never as a substitute for the orchestrator's own verification (Phase 4),
  and never to review work that already passed its acceptance criteria. If a
  loop is reaching for a third consult, the plan is the problem - stop and
  re-plan rather than buying more opinions.

## Phase 3 - Delegate (workers, parallel)

- One `Agent` call per subtask, **`model: "opus"`**, in a single message so
  they run concurrently; background by default. Opus is the default because a
  worker's output is only as trustworthy as the model that wrote it, and the
  orchestrator verifies from evidence - it does not re-do the work. A weak
  worker does not save money; it moves the cost into re-delegation, missed
  edge cases, and defects the verify step is not guaranteed to catch.
- **The sonnet exception.** Drop a single subtask to `model: "sonnet"` only
  when it is genuinely low-stakes on every count: mechanical and fully
  specified (no judgment calls, no design decisions), trivially reversible,
  its acceptance criteria machine-checkable (tests, a diff, an exact string),
  and a wrong result is cheap and obvious rather than silently wrong.
  Examples that qualify: a mechanical rename sweep, a formatting pass, a
  file-listing or grep-collation errand. If any one of those conditions is
  arguable, use opus. Never downgrade a whole fan-out at once - the exception
  is per-subtask and the orchestrator states the reason in the plan.
- Each worker prompt is self-contained: context, exact deliverable,
  acceptance criteria, what NOT to touch. Workers never spawn workers and
  never expand scope.
- Two workers must not write the same file - that seam belongs to the
  orchestrator or to sequencing.

## Phase 4 - Verify (orchestrator)

Check each result against its acceptance criteria using evidence, not the
worker's summary. Reject → re-delegate once with tightened criteria and the
specific failure named. Second failure, or a failure that is ambiguous about
whose fault it is (plan vs worker) → escalate to the advisor with the
transcript evidence. Never synthesize an unverified claim.

## Phase 5 - Synthesize (orchestrator)

One coherent deliverable in the final message - resolved, deduplicated,
in-voice - not a concatenation of worker reports. For user-facing or
high-stakes output, an optional advisor taste pass before shipping - within
the Phase 2 budget, not on top of it.

## When NOT to use

Single-file edits, single-step tasks, tasks under ~3 independent subtasks,
or anything where reading the fan-out reports would cost more than doing the
work. The loop pays for itself only when workers run in parallel.

## Related tooling

`advisor` agent (this skill's off-path judgment and counsel),
`supervisor` agent via cover-me (in-flight watcher, push not pull).

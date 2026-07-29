---
name: reflect
description: End-of-session truth reconciliation. MUST be used when the user types /reflect, says "reflect", "reconcile", "let's reconcile", "before we wrap up", "close out the session", or at any session closeout or wrap-up moment - the sweep is a defined procedure with a user-approval gate, not an ad-hoc summary. Sweeps the session for anything newly learned, discovered, chosen, decided, or discussed that (a) should become permanent memory, or (b) invalidated an existing stated claim in any docs, comments, configs, or memory - then correct those so everything lines up with current truth. Distinct from /notes (the docs sweep): reflect promotes durable knowledge to memory and fixes stale claims, then hands off to /notes.
---

# Reflect - session truth reconciliation

A deliberate pause before closeout to ask two questions about everything this
session surfaced:

1. **Is any of it durable knowledge that should outlive this session?** → promote
   it to permanent memory.
2. **Did any of it invalidate something already written down as true?** → find that
   stale claim wherever it lives - memory, docs, comments, configs - and correct it
   so the whole record lines up.

Reflect is about *truth*, not documentation. It is **not** `/notes`. `/notes`
sweeps session work into the repo's living docs; reflect promotes durable facts to
memory and reconciles stale claims, then *reminds* you about `/notes` rather than
doing its job.

**Reflect proposes; the user approves; then reflect applies.** It never writes a
memory or edits a file off its own conclusions - every belief it intends to commit
is surfaced to the user for validation first. The user owns what becomes permanent
truth.

Run when invoked as `/reflect`, when the user says "reflect" / "reconcile" /
"close out the session", or proactively when wrapping up substantive work.

## Step 1 - Reconstruct what's new

Think back over the whole session and list, concretely, what changed in your
understanding of the world - not what you *did* (that's `/notes`), but what is now
**true or known** that wasn't before:

- **Learned / discovered** - non-obvious facts about the code, tools, environment,
  or the user's intent that weren't written anywhere.
- **Chosen / decided** - choices made and the *why* (the reasoning, not just the
  outcome).
- **Discussed** - preferences, corrections, or guidance the user gave on how you
  should work.
- **Changed** - anything that makes a previously-true statement now false.

Pull from the actual conversation and the working tree. **Validate before writing -
do not invent insight that wasn't really there.** If the session produced nothing
durable and contradicted nothing, say so and skip to Step 4.

## Step 2 - Compile the proposals (no writes yet)

Build the full slate of what you *would* change - but **do not write or edit
anything yet**. Two buckets:

**A. Durable knowledge → route it, then draft.** A live PreToolUse hook
(`memory-routing.sh`) fires the same question on every new memory write, and a
PostToolUse `memory_lint.py` fails the write if the file lacks a `MEMORY.md`
pointer or valid frontmatter - so route BEFORE proposing, or the gate catches it
after. For each keep-worthy item, name the category first:

- (a) specific to THIS repo → memory (proceed). (b) a universal working
  principle → global `~/.claude/CLAUDE.md`, not memory. (c) an invariant to
  ENFORCE → a hook. (d) a reusable procedure → a skill. (e) a client/project
  fact → that project's own docs, NEVER memory (a copy here has no staleness
  detection and will silently contradict the source). Only (a) becomes a memory.

Then draft the memory entry per the rules in `~/.claude/CLAUDE.md`:

- One fact per file, frontmatter (`name` matching the filename stem,
  `description`, `metadata.type` = `user` | `feedback` | `project` | `reference`).
- **Reconcile, don't duplicate.** Check for an existing memory file that already
  covers it - propose an *update* to that file rather than a near-duplicate.
- New files get a one-line `MEMORY.md` pointer; `feedback` / `project` entries get
  **Why:** and **How to apply:** lines; link related memories with `[[name]]`.
- **Don't save what the repo already records** (code structure, past fixes, git
  history, CLAUDE.md, README.md's architecture section). If it belongs in repo docs, that's a
  `/notes` job - set it aside for Step 5. Memory is for what *isn't* derivable from
  the tree. (claude-mem auto-captures tool calls; you don't hand-feed it.)

**B. Stale claims → corrections.** The session may have made an existing written
statement **false**. Hunt them down - grep for the old name/value/claim across the
tree so you find every site, not just the one you remember:

- **Memory** - existing files that now contradict the truth (update, or flag for
  deletion if simply wrong).
- **Docs** - `SPEC.md`, `README.md`, `tasks/plan.md`, `tasks/todo.md`,
  `tasks/SPEC-*.md` (or legacy root `PLAN.md` / `HANDOFF.md`), any in-repo
  `*.md` asserting something the session changed.
- **Code comments** - comments describing behavior the session altered are now lies
  in the source.
- **Configs** - settings, manifests, scripts encoding a now-stale assumption (a
  renamed path, a dropped flag, a changed default).

For each, capture the `file:line`, the old text, and the proposed new text. This
step produces a *plan*, not edits.

## Step 3 - Play it back and get validation (gate)

Surface **everything** to the user before applying any of it - the
"repeat back to me everything you think you heard and learned this session" moment.
Present the complete slate, grouped and skimmable:

- **What I now believe is true** - each durable fact, in plain language, with where
  it came from in the session, and the memory file it would create/update.
- **What I think went stale** - each contradicted claim, shown as
  `file:line` → old → proposed new.
- **Deletions** - any memory file you believe is now wrong and would remove, with
  why.

Then **stop and wait.** The user confirms, edits, or drops items - these are *their*
beliefs becoming permanent truth, so nothing is written without an explicit go.
Apply **only** what they approve; carry their wording changes through verbatim.

## Step 4 - Apply the approved changes

Write the approved memory entries and corrections, exactly as validated:

- Memory files + `MEMORY.md` pointers per `~/.claude/CLAUDE.md`.
- Surgical edits to docs/comments/configs - preserve surrounding voice and unrelated
  content. **Read before edit; non-destructive always.**
- Where an approved fix is bigger than a surgical correction (a doc wants
  restructuring), do only what was agreed and flag the rest.

## Step 5 - Closeout tickle (hand off to /notes)

After reconciliation, decide whether documentation work still remains - i.e. the
session produced completed/changed/implemented work that belongs in the repo's
living docs via `/notes` (which reflect deliberately does **not** do).

- **If yes:** tell the user reflection is done and that `/notes` looks warranted,
  then **ask** - run `/notes` now, or keep working first? Do not auto-run it.
- **If no:** say reflection is complete and nothing further is queued.

## Step 6 - Report

Summarize concisely:

- **Applied** - memory files created/updated/deleted and stale claims corrected
  (with `file:line`), reflecting only what the user approved.
- **Dropped** - proposals the user declined or amended.
- **Deferred** - anything intentionally left (e.g. a restructure that needs the
  user's call).
- **Next** - the `/notes` tickle and the user's choice, or that nothing's queued.

## Guardrails

- **Propose before applying.** Nothing is written until the user has seen the full
  slate and approved it. Reflect surfaces beliefs; the user ratifies them.
- **Non-destructive.** Read before edit; merge, never gut. Use `__archive/` for
  soft-deletes of user content; delete only memory files that are genuinely wrong -
  and only with approval.
- **Don't name the user** in any memory, doc, comment, or config.
- **Validate before concluding.** Web-search or grep before asserting; never bluff a
  reconciliation you haven't confirmed.
- **Reflect ≠ notes.** This skill touches memory and corrects stale claims; it does
  not perform the docs sweep - it hands that to `/notes` with the user's consent.
- This skill does not commit or push unless the user asks.

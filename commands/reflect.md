---
description: Session-closeout memory reconciliation - sweep the session for anything newly learned, chosen, or discovered that should become permanent memory, correct or remove memories it made stale, prune the index, then tickle /notes for any stale claim in the repo itself.
---

Invoke the `reflect` skill.

Before closing out this session, reconcile what it surfaced against what memory
holds. **Propose everything first - apply nothing until the user approves.**

1. **Reconstruct** - list what's now *true or known* that wasn't before: learned,
   discovered, chosen, decided, discussed, changed. Pull from the conversation and
   the working tree; validate, don't invent.
2. **Compile proposals (no writes)** - draft, but don't apply: (a) durable facts to
   promote to the file-based memory store and its `MEMORY.md` index (per the memory
   rules in your `~/.claude/CLAUDE.md`), reconciling with existing files instead of
   duplicating, skipping anything the repo already records; (b) memories the
   session made stale, as `file:line` → old → proposed new; (c) removals and merges
   per the skill's count tiers. A stale claim in the repo's own files is noted
   for `/notes`, never edited here.
3. **Play it back and gate** - repeat back to the user everything you think you
   heard and learned: each new belief and where it came from, each stale memory as
   `file:line` → old → new, and any memory you'd delete. Then **stop and wait** for
   confirmation. These are the user's beliefs becoming permanent truth.
4. **Apply only what's approved** - write the ratified memory entries and
   corrections, carrying any wording changes through verbatim.
5. **Tickle /notes** - if documentation work or an in-repo stale claim remains,
   tell the user and **ask**: run `/notes` now, or keep working first? Don't
   auto-run it.

The natural-language remainder of the request refines focus. Non-destructive
throughout: read before edit, never name the user, delete only memory that's truly
wrong and only with approval. Report what was applied, what the user dropped, what's
deferred, and the `/notes` decision.

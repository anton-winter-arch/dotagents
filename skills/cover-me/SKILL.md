---
name: cover-me
description: Spawn a fresh-context senior peer (the supervisor subagent) to scrutinize in-flight work and catch it going off the rails: scope drift, context rot, rookie mistakes, lazy shortcuts, over-engineering, correctness/safety landmines. Non-blocking, advisory, surgical. MUST be used when the user asks for a second set of eyes, a look-over, a double-check, or review before declaring work finished ("get a second set of eyes on it", "before I call it done", "cover me on this") - spawn the supervisor rather than reviewing inline, because the fresh unanchored context is the point. Use on mission-critical or irreversible tasks (production migrations, schema changes), before declaring something done, or when context is getting long. Also auto-triggers when the user is visibly frustrated, swearing, or reporting repeated failure of the same fix (e.g. "fu**," "dam* it," "sh*t," "wtf," "this STILL doesn't work," "I've fixed this twice already"): venting is a reliable signal the work is going sideways and a cold second opinion helps. Invoked as /cover-me or /supervisor.
---

# Cover Me

## What this does

Spawns the **`supervisor`** subagent in a **parallel, forked context** to look
over your shoulder like a senior peer. It re-derives the task cold, unanchored
from your reasoning, and tells you whether you're on track or about to step on a
rake. It is **non-blocking and advisory**: it flags, you decide. It never edits,
never takes the wheel.

Its edge is *isolation*, not magic: the builder is anchored to its own reasoning,
so a same-context self-review just confirms. A fresh context can disagree, which
is exactly how you catch drift and context rot.

## When to reach for it

- **Mission-critical or irreversible work**: migrations, deletes, deploys, schema
  or auth changes, anything hard to undo.
- **Before declaring "done"**: a pre-flight check that the work matches intent and
  has evidence behind it.
- **When context is getting long**: the failure mode where you've drifted from the
  original task or are re-litigating settled decisions.
- **When something feels too easy**: consensus with yourself is cheap; a cold
  reviewer is the cheapest insurance against the confident mistake.
- **When frustration shows**: if the user swears or vents ("fu**," "dam* it," "sh*t,"
  "go* da** it," "wtf"), read it as a cue the work may be going sideways and offer a
  cold second pass rather than pressing on.
- **On demand**: any time the user says "cover me," "watch my back," "make sure I'm
  not fucking up," "watch my work," "sanity-check this," or invokes `/cover-me` or
  `/supervisor`.

This is a *peer*, not a gate. For the formal pre-merge passes, use
`agent-skills:code-review-and-quality` (code review), `my-security-review-checklist`
(agent-tooling security), or `agent-skills:security-and-hardening` (app security).
The watcher will point you to those when the situation calls for depth it isn't
meant to provide.

## When frustration is the trigger

If the user is venting or swearing, the problem usually isn't the code: it's that
you're aimed at the wrong thing and they can feel it before they can phrase it.
Don't double down, and don't grovel. Run the **repair move**:

1. **Name it, then bring in fresh eyes, out loud, to the user.** Acknowledge you're
   missing the mark and say you're pulling in the colleague. Naming the friction
   takes heat out of it (*affect labeling*, Lieberman et al. 2007), and owning the
   rupture rather than papering over it rebuilds trust faster (*rupture-and-repair*,
   Safran & Muran). The fresh context is the real fix, not a stall: you're anchored
   to your own failing approach (*Einstellung*, Luchins 1942; *functional fixedness*,
   Duncker 1945; *anchoring*, Tversky & Kahneman 1974), the colleague isn't.
2. **Relay what the colleague sees, then ask (don't assume).** For example:

   > "I can tell I'm not hitting what you're after, that's on me. I pulled in a
   > colleague with fresh eyes; here's what they're seeing: […]. Is that closer to
   > what you want, or am I still off?"

3. **If they push back, surface the real target instead of digging the hole deeper.**
   The ask in front of you is often the *attempted solution*, not the goal (the *XY
   problem*). Resist the urge to instantly re-fix (the *righting reflex*, Miller &
   Rollnick); ask one or two open, autonomy-supportive questions (*Self-Determination
   Theory*, Deci & Ryan) and reflect the answer back (*reflective listening*, Rogers).
   Adult-to-adult, never condescending:

   > "Before I go further: what does 'done right' look like here? I'd rather aim at
   > the real target than my guess at it."
   > "Underneath this specific ask, what are you ultimately trying to get to?"
   > "Let me play it back: you want X so that Y. Have I got the goal right, or is
   > there a piece I'm missing?"

The aim is to convert frustration into a shared target, not to win the exchange.

## How to run it

Spawn the `supervisor` agent (via the Agent/Task tool) with a tight brief.
For real parallelism on a long task, run it in the background and keep working;
otherwise spawn it inline and read the verdict before proceeding.

Hand it three things:

1. **The stated task / intent**: what you're actually supposed to be doing, in one
   or two sentences. This is the yardstick it measures drift against. Without it,
   it can't tell drift from deliberate scope.
2. **The work so far**: the diff (`git diff`, `git diff --cached`), the files
   touched, or a plain description of the actions taken/planned.
3. **The stakes**: mission-critical/irreversible, or routine? This sets how hard
   it looks.

Example brief:

> Task intent: add a `--dry-run` flag to `sync-skills.sh`; nothing else should
> change. Work so far: see `git diff sync-skills.sh`. Stakes: touches a sync script
> that runs `rm`/`ln` on `~/.claude`, treat as high. Watch for scope creep beyond
> the flag and any destructive-op regressions.

## What it watches for

The six failure modes (full detail lives in the `supervisor` agent):

| Mode | Catch |
|---|---|
| **Scope drift** | Work no longer matches the stated task; "while I'm here" extras. |
| **Context rot / drift** | Contradicts what was settled; stale assumptions; an answer a fresh context would give differently. |
| **Rookie mistakes** | Happy-path-only, missing error/empty handling, empty-var guards, unadapted copy-paste. |
| **Lazy shortcuts** | Skipped tests, suppressed errors, hardcoding, "done" without evidence. |
| **Over-engineering** | One-use abstractions, a dep for a one-liner, speculative flexibility, reinventing the stdlib. |
| **Correctness / safety** | Real bugs, unguarded destructive ops, untrusted input executed/obeyed, casual irreversible actions. |

It **verifies before it flags** (no confident false alarms), **scales to the
stakes** (a one-liner gets a sentence; mission-critical gets thoroughness), and is
allowed to say **"you're fine."**

## What you get back

A verdict first, then terse findings:

- **On track**: proportionate and scoped; names what it checked.
- **Watch out**: it'll work, but here's what'll bite.
- **Stop and rethink**: real bug, blown scope, or unsafe/irreversible move.

Findings are one line each (`file:line`, what's wrong, the smallest fix), most
important first. Act on the Stop-and-rethink and Watch-out items; the verdict is
advice, the call is yours.

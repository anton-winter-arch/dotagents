---
name: goldfish
description: >-
  goldfish is a light review of a SPEC*.md and its related tasks/plan.md before
  implementation. It launches a fresh-context reader subagent that has never
  seen the session. It reads the spec, the plan files for the implementation,
  and the related code files (if any exist), and it lists every point that's
  not clear to a cold reader - everything an implementer would have to guess,
  every reference that does not resolve and every contradiction, then raises
  them so the session agent can fix the spec and plan. Use the goldfish skill
  early or mid session when a spec or plan is about to be implemented, when the
  user asks to goldfish a spec, or to pressure-test, sanity-check or hole-poke a
  spec and its plan for ambiguity. This is good to run if the user asks whether
  a spec is ready to build from. It takes a path or a few words naming the spec.
  Otherwise ask the user which spec to goldfish. This skill should run quickly.
  goldfish is not a substitute for PR reviews, security reviews, wrap up, etc.
argument-hint: "[fable|opus|sonnet|haiku] <spec path or a few words naming it>"
---

# goldfish

The session that wrote a spec reads into it what it knows from its own context.
A reviewer with none of that context finds the gaps before an implementer, or
this session after a compaction, falls into them.

Specs in this repo's `tasks/` right now:

!`ls tasks/SPEC-*.md 2>/dev/null || echo "(no tasks/SPEC-*.md here)"`

## Procedure

1. **Find the spec.** The argument is a path or a few words ("the agent team
   spec"). Match words against the list above by file name and, if needed, by
   each file's title line. One clear match: use it and name it. More than one:
   ask with AskUserQuestion, listing the candidates. None: say so and stop.
2. **Pick the model.** If the first word is `fable`, `opus`, `sonnet` or
   `haiku`, pass it as the Agent call's `model`. Otherwise pass none; the
   `reader` definition sets Sonnet. Say which model ran.
3. **Pick the files.** Beside the spec, add as paths:
   - the plan files that drive its implementation: the handoff or plan
     sections that name this spec or its phases, such as `tasks/todo.md`;
   - every code, config or test file the spec and those plans name, or name by
     function or command, resolved to a path. Files only, never the whole repo,
     and never `.env*`, keys or other credential files.

   State the list in one line before spawning.
4. **Spawn the `reader` subagent** with a brief that carries task content only,
   the file list and the task below, and nothing from the session:

   > Read only these files. You will implement the spec from them alone,
   > starting tomorrow, with no one to ask. Report, each with its file and line:
   > 1. Every point where you would have to guess: a term used before it is
   >    defined, an "as before" or "the existing X" with no file named, a format
   >    or rule stated loosely.
   > 2. Every reference that does not resolve: a path, function, flag, command
   >    or format the docs name that the code does not have or has differently.
   > 3. Every contradiction, between the docs or between a doc and the code.
   > 4. The first step you would take, and anything blocking it.
   > Rank by how badly each would derail the build. Say plainly when a category
   > is empty. Do not suggest features or restyle prose.

5. **Fix the docs, not the chat.** Answer each finding by editing the spec or
   the plan so the answer is written down; dismiss one only with a reason.
   Check a finding against the files before acting on it, since the reader can
   misread too. Rerun once on the edited files, and stop when a pass finds
   nothing that would derail the build. Report what changed in a few lines.

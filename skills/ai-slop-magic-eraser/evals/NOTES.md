# Reading this skill's trigger evals

Measurement caveat, verified 2026-10-06: `run_eval.py` scores a miss the moment
the probe's first tool call is anything but Skill or Read, and a Read counts
only when it opens the probe's own copy of the skill. Every positive case here
names a file (`draft-spec.md`), and the model's correct first move is to find
or read that file. A probe replayed with the real skill installed ran
`Bash: find`, then `Read draft-spec.md`, then `Skill ai-slop-magic-eraser`,
which forked into the `curator` agent as intended. The harness had already
scored that run a miss at the first call.

On claude-sonnet-5 the five positives scored 0/5 with the current description
and 0/5 with the previous one, so the number measures the harness, not the
description. The four negatives scored 4/4. The positives are not a pass gate
for this skill.

Consequences:

- The should-NOT cases are the enforceable half: they draw the boundary against
  arguing a different position, code cleanup, UI slop and fresh drafting. Keep
  them passing.
- Judge recall by probing with the fixture present and reading the full tool
  sequence from `claude -p --output-format stream-json`, not by this harness's
  positive-case numbers.
- Do not rephrase the positive cases into invocation-shaped prompts to make the
  numbers move; that games the meter and degrades the cases as documentation of
  real usage.

The behavior eval for the curator lives beside these cases in `curator/`, graded
by `scripts/grade_curator_eval.py`.

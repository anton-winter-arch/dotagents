---
description: Implement incrementally - build, test, verify, commit one thin slice at a time (agent-skills incremental-implementation).
---

Invoke the `agent-skills:incremental-implementation` skill.

Deliver the change in thin vertical slices: implement the smallest complete
piece, test it, verify it, then expand. Never batch unverified changes. Run the
regression suite after each slice. Add "auto" to run the whole plan in one
approved pass.

$ARGUMENTS

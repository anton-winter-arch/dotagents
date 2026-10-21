# focus battery

The eval harness cannot stage a sprawled session, a subagent spawn and the distil script, so the cases in `evals.json` are graded in vivo: the first `/focus` the user fires that matches a case is the graded run for it. A run the agent starts itself, to check the plumbing, is a dry run and is recorded as one, never as a graded pass. Record one line per run here, newest first, with the case id or "dry run", the date, the verdict relayed, and a pass or fail against the case's expectations. A failed line names the expectation that failed; the fix goes into `SKILL.md` or `agents/supervisor.md`, and the case is regraded on the next run the user fires.

Pass means: exactly one request list, relayed not rewritten, every request cited to a position, fewer live threads after the reply than before it, and the turn ending where the case says it ends.

## Runs

- 2026-10-20, dry run (agent-started, in the authoring session), verdict Watch out, report `tasks/supervisor/2026-10-20-focus-build-dry-run.md`. The plumbing worked end to end: distil, spawn, a verdict in the specified shape with every request cited. It found the distiller dropped the user's mid-turn message and cut the opening request at 500 characters; both fixed the same day with tests. Not a graded case; case 1 waits for a user-fired run.

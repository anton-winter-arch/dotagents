---
name: wrap-up
description: Close a session cleanly so the next one starts strong - review the session's files, bring the docs and the handoff up to date, commit and push on the right branch, then write memory. MUST be used when the user closes out a SESSION, however phrased - wrap up, end the session, close it out, that is everything for today - and whenever they name three or more of security review, inbox, reflect, notes, commit, sync and push together. Session scope is the discriminator - wrapping up a task, a feature or a bug is not this, a mid-session save is not this, and a single verb alone belongs to its own skill. Also on /wrap-up.
---

# wrap-up

When this ends, the session's files are reviewed, every claim in the repo is true, the tree is committed and pushed on the right branch, memory holds what was learned, and `tasks/todo.md` holds everything the next session needs. Nothing it needs is left only in this conversation.

This skill owns the order and nothing else. Each sub-skill and agent owns its procedure and gates, and this file does not restate them: `my-security-reviewer` owns the review, `notes` the repo's text, `repo-device-sync` git, and `reflect` memory. Where one is not installed, its step is done by hand and the report says so.

## It runs once per session - never loop

The review runs once, at the end. Its findings get fixed or dismissed, and then it is over:

- Never send the fixes back for another review.
- Never start wrap-up again because the fixes changed files.
- Never treat a reviewer's or curator's suggestion as new work that needs another pass.

Fix, close, commit, push, end. `review_gate.py` holds this for you. `close` (step 5) records the tree once every finding is settled. `check` (step 1) compares the tree with that record:

- **PASS:** nothing changed since the review closed. Skip steps 2 and 5. Commit what is uncommitted, or report and end.
- **REVIEW:** it lists the files changed since the close. Those files are the only scope. A small follow-up (a typo, a doc line, a fix from the review) is an ordinary commit with no review. Review again only when the list shows major edits to other files, or new files, made after the push. That is rare. Then tell the user the session has run past its closeout, and suggest `/clear` or a new session for further work.

## 1. Assess

```bash
git status --porcelain && git fetch origin && git status -sb && git branch -vv
python3 "<skill-dir>/scripts/review_gate.py" check   # PASS: the review already ran on this tree
```

Stop if there is nothing to wrap up, if the tree holds changes this session did not make (ask before staging them), or if the branch has diverged (run `repo-device-sync` Phase 3 first).

## 2. Review, in the background

List the session's files from `git status --porcelain` and the unpushed range (a new skill counts as its whole folder), sweep them, and fix each FAIL. A false positive (a stand-in value, or a line the session did not change) is named in the report with its reason instead; never rerun the sweep hoping for clean.

```bash
python3 "<skill-dir>/scripts/closeout_lint.py" <files>   # exit 1 on FAIL
```

Run the session's tests once, scoped to what changed; never a whole-repo sweep. The script maps each changed file to the one suite or test that covers it, runs them on the Python 3.9 floor (`--both` adds the newest), skips any check that already passed on the same content, and exits 1 on a failure. After a fix, rerun it with `--files` naming only the fixed files.

```bash
python3 "<skill-dir>/scripts/affected_tests.py"            # --list to see the plan first
```

Run the resource check beside it.
- The spawn lint covers the session's files. A finding is fixed like a FAIL.
- The reaper reports heavy processes left running with no owner. A finding goes in the report and to the user; nothing is stopped without their yes.

```bash
python3 "<skill-dir>/../skill-authoring/scripts/check_spawns.py" <files>   # exit 1 on a finding
timeout 30 python3 ~/.claude/hooks/reaper.py --report                       # skip if the hook is not installed
```

Write the list, one diff of those files and the sweep (`--json`) to the scratchpad and spawn `my-security-reviewer` with the three paths. Pass `model: sonnet` unless the list holds executable surface (scripts, hooks, settings, a new skill) or a claim about the outside world (a package, endpoint, version). Skip the review only when the list is under ten prose files, none under `skills/`, `specs/`, `agents/`, `commands/` or `app/`, and the sweep is clean.

Spawn `curator` alongside it only when the user asks for a presentation pass, over the changed reader-facing files that `notes` does not write: skill bodies, references, agent and command files, and published docs. Its scope never includes frontmatter, `README.md`, `SPEC.md` or `tasks/`.

Do steps 3 and 4 while the agents work, and never poll or re-spawn them.

## 3. Inbox

Only when the session-start notice reported unprocessed mail, or the user asks: run `agent-mail`, and name in the report what is still open.

## 4. Notes

Run `notes`.

## 5. Join and fix

Take the reviewer's verdict, and the curator's report when one ran. Fix each finding with the smallest edit and a test, rerun `affected_tests.py --files` on the fixed files only, and re-sweep what changed. Only a finding the fix cannot settle goes to the user, and nothing commits with a finding open. What the reviewer could not verify is checked here or put to the user.

Then close the review. Write each finding to a JSON list as `{"finding", "status": "fixed" | "dismissed", "reason"}`; a dismissal needs a reason. Write `[]` when there were no findings or the review was skipped.

```bash
python3 "<skill-dir>/scripts/review_gate.py" close <findings.json>   # exit 1 while a finding is open
```

## 6. Commit and push

```bash
python3 "<skill-dir>/scripts/gitignore_audit.py" audit   # exit 1 on findings
```

Each uncovered pattern goes to the user before staging. Then run `repo-device-sync` from Phase 2 through Phase 4, as one commit.

## 7. Reflect

Run `reflect` last. A stale in-repo claim it finds goes in the report as follow-up work: nothing in the repo is edited or committed after the push.

## Report

Report in one block: the verdict and what was fixed or accepted; the resource check; anything unverified and its outcome; the curator's edits and the inbox result, when those steps ran; what notes moved and the hot-file line counts; the commit hash and each ref's position; what reflect wrote or removed; anything undone; every gate and the user's decision.

## Never

- Merge a branch or PR, or publish to the mirror unless the user says so in that message.
- Skip a sub-skill's gate, or commit with an unresolved security finding.
- Review the review's own fixes, or restart wrap-up after `review_gate.py` printed `CLOSED`.
- Stop a process the reaper reports without the user's yes.

---
name: repo-device-sync
description: Multi-device git sync ritual for repos worked on from several machines, sometimes concurrently. Fetches and diffs origin before work starts, reconciles inbound commits from other devices, re-fetches immediately before every push, and verifies branch parity (e.g. develop == main == origin) afterward. Divergence is a stop-and-ask condition - never force-push, rebase shared history, or hard reset. In ~/.agents it adds an optional station drift-check against SPEC-CLAUDE.md. MUST be used for ANY push or pull intent in a repo worked from multiple machines, however casually phrased - "ok push this up", "done for the night - ship it", "anything to pull from my other machine?", "check the remote before we start" - do not just run git directly; the ritual (re-fetch, reconcile, verify parity) is the point. Also after a sync reports divergence, and on "/repo-device-sync" or "sync the repo".
---

# repo-device-sync

Keeps one repo consistent across devices that may commit concurrently. The
failure this prevents: starting work on stale state, or pushing over a commit
another machine landed mid-session. The discipline is always the same -
**fetch before trusting anything, diff before pulling, re-fetch before
pushing, verify after.**

## Phase 1 - Assess (always first)

```bash
git status --porcelain      # uncommitted local work?
git fetch origin            # never reason about origin without this
git status -sb              # ahead/behind for current branch
git branch -vv              # ahead/behind for all tracked branches
```

Report per tracked branch: in sync / ahead N / behind N / diverged (N and M).
Surface uncommitted changes before doing anything else - they change what is
safe below.

## Phase 2 - Reconcile inbound (behind)

1. Show what is coming: `git log --oneline HEAD..origin/<branch>` and a
   summarized `git diff HEAD...origin/<branch> --stat`.
2. Clean fast-forward (no divergence, no conflicting uncommitted files):
   `git pull --ff-only`. Proceed without asking - this is the point of the
   ritual and it is the reversible direction.
3. Uncommitted changes that overlap the incoming diff: stop, show the
   collision, ask (stash / commit first / abort).

## Phase 3 - Diverged (stop-and-ask)

Divergence means both machines committed. Never resolve it silently.

1. Show both sides: `git log --oneline origin/<branch>..HEAD` (local-only)
   and `git log --oneline HEAD..origin/<branch>` (remote-only), plus stat
   diffs of each.
2. Propose a strategy - normally `git pull --no-rebase` (merge); flag any
   files touched on both sides. Do not run the merge (or anything else
   history-changing) until the user chooses.
3. **Hard rules:** no `push --force`/`--force-with-lease`, no rebasing
   already-pushed commits, no `reset --hard`, no stash-drop, no
   `git clean -f`, no branch deletion (`branch -D`, `push --delete`), no
   `checkout --`/`restore` over uncommitted work. If the user wants history
   rewritten or work discarded, that is their call to make explicitly.

## Phase 4 - Outbound (before every push)

1. **Re-fetch immediately before pushing** - the fetch from Phase 1 is
   stale; another device may have pushed mid-session. If origin moved, loop
   back to Phase 2/3 first.
2. Push, then verify: `git fetch origin && git status -sb` shows in-sync.
3. Branch-parity convention: if the repo keeps a pair of branches equal
   (e.g. develop == main here), fast-forward the trailing branch and push
   both, then confirm all four refs (2 local + 2 origin) point at the same
   commit: `git rev-parse develop main origin/develop origin/main`.

## Phase 5 - Station drift-check (optional; ~/.agents only)

After a clean sync in ~/.agents, or on "check the station against the spec":

1. Read `SPEC-CLAUDE.md` at the repo root - it is the source of truth for
   the station (plugins, CLI deps, global CLAUDE.md/settings templates,
   hooks, permission rules).
2. Inspect live state: `claude plugin list` (or `~/.claude/plugins/`),
   `~/.claude/settings.json`, hook config, required CLI deps
   (`rtk --version`, `jq --version`, claude-mem daemon).
3. Report drift as a per-item diff: spec expectation vs live state, plus
   which side is newer (per-machine files re-seed FROM the spec; spec
   changes come from deliberate edits, not drift).
4. **Non-destructive:** propose fixes, apply nothing without approval.

## Report format

End with a compact table: branch → state found → action taken → final state.
One line for uncommitted work, one for the drift-check verdict if run.

## When NOT to use

General git questions, single-device repos with no concurrent-edit risk,
in-repo branch/merge work that never touches origin. This skill is the
origin-facing ritual only.

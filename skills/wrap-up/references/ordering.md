# Why the chain runs in this order

Each step's output is the next step's input, so the sequence is not arbitrary.
Numbers are the step numbers used by SKILL.md's headings, so they start at zero.

0. **Fetch before anything.**
   Inbound commits from another machine can change what is true.
   Documenting the session against stale state produces doc corrections and memory entries that are wrong on arrival.
   This is the one place the obvious order - work first, git last - is wrong.

1. **Security review and the curator start first and run in the background.**
   The reviewer reads only the files the session created or edited, which the main agent lists for it.
   The session's code is finished by the time the closeout starts, so the review has nothing to wait for, and starting it first means its verdict is usually in by the time the docs are.
   A focused list is what keeps it short: a reviewer told to judge "everything since the last push" spends its budget discovering scope and reports on a tree that has already moved.
   The curator takes the reader-facing files on the same list that notes does not write and rewrites how they read, never what they say, so nothing waits on it either.

2. **Inbox before notes.**
   Unprocessed peer mail carries decisions, findings and corrections from other agents.
   Documenting before draining it produces docs that a message in the inbox already contradicts.

3. **Notes overlaps the review and the curator.**
   The three own disjoint slices: the reviewer judges the session's files, the curator owns how the session's published prose reads, and notes edits the repo's docs and corrects any in-repo text the session made false.
   A notes correction or a review fix to a file the curator holds waits for the curator's report, so two writers never edit one file at once.
   The curator also never edits frontmatter, since tools, model and description set privileges and routing for every future session.

4. **One join point, before staging.**
   The commit needs the verdict with its fixes applied, the curator's edits read as a diff, and the finished docs.
   Notes' and the curator's edits landed after the reviewer started, so the join lints them mechanically and sends notes' files outside `tasks/` and the curator's diff to the re-review, which keeps the two-round cap: a linter cannot decide whether published prose names something private.

5. **Ignore audit, then commit, then push, with a second fetch between.**
   Notes is the last step that creates files in the repo, so the audit sees the whole set the commit would stage.
   Before the commit an uncovered cache or env file is one question and one ignore line; after it, the file is in history and comes out only with a second commit that deletes it from every other clone.
   The fetch from step 0 is stale by now; another machine may have pushed during the session.

6. **Branch parity**, because it advances a branch to a commit that must already exist on the remote.

7. **Reflect last.**
   Memory lives in the harness's project folder, outside every repo, so nothing in the git steps depends on it and writing it after the push leaves the tree clean.
   Everything reflect used to correct inside the repo now belongs to notes, which runs before the commit.
   Memory is also the slowest step to approve, so putting it last means a long slate review never holds the push.

## Why step 0 is safe to run before any decision

The four `status`, `symbolic-ref` and `branch` reads are pure reads.
`git fetch` writes only remote-tracking refs under the git directory, so it cannot touch the working tree, local branches or commits.

`origin/HEAD` is often unset, in which case `symbolic-ref` fails and `git branch -vv` is the real evidence of branch shape.

## What only the security review catches

Two classes reach nothing else in the chain.

**Secrets and personal or station-specific constants** that a later step is about to publish.
Cheap to remove now, permanent once pushed.

**Changes to the agent tooling itself** - hooks, sync scripts, subagent definitions, settings files - where the blast radius is every future session on every machine rather than this repo.
That is why the review is not optional when the session touched shared tooling: it is the gate standing between a mistake and a fleet-wide one.

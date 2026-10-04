---
description: Full session closeout - a focused security review of the session's files in the background while the inbox and notes run, then commit, sync and push, then reflect writes memory last, ending with a clean tree on the branch the repo's workflow says work belongs on.
---

Invoke the `wrap-up` skill.

Close out this session end to end. The skill owns the sequence, the handoffs and
the guards; each sub-skill owns its own procedure.

0. **Assess and fetch first.** Stop and ask if the tree holds changes this session
   did not make, stop if origin has diverged, and say plainly if there is nothing
   to wrap up.
1. **Start the security review in the background** over the list of files this
   session created or edited - the main agent builds the list, the reviewer does
   not go looking.
2. **Inbox, then `notes`** while the review runs. Notes updates the living docs and
   corrects anything in the repo the session made false.
3. **Join** on the verdict and the finished docs, then the ignore audit and
   `repo-device-sync`: one commit, re-fetch, push, land on the right branch.
4. **`reflect` last.** Memory lives outside the repo, so it never dirties the
   pushed tree.

Every agent in the chain owns one slice and keeps it moving; nobody re-checks
another's slice. The natural-language remainder of the request refines focus, for
example naming the commit message or asking for more than one commit.

Never force-push, rebase pushed history, hard reset, or push to a public mirror.
Preserve every sub-skill's own gate. Finish by confirming the tree is clean,
reporting each ref's final position, and naming anything deliberately left undone.

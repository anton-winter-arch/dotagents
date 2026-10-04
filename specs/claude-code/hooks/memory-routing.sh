#!/usr/bin/env bash
# PreToolUse(Write|Edit|Create|Update) - memory-write ROUTING nudge and folder
# cap. Fires when a NEW file is about to be created under a memory dir
# (~/.claude/projects/<slug>/memory/*.md) and asks the routing question before
# the belief is written - the category that a yes/no "are you sure" prompt
# failed to surface.
#
# Tiers, keyed on the folder's memory count after the write (MEMORY.md excluded):
#   under 50  allow, routing question only
#   50-74     allow, plus a hygiene prompt (prune, rules in disguise)
#   75-100    allow, plus "only if important and unique, else extend"
#   101+      DENY - a new memory needs a slot: an approved removal comes first
#
# Only new files: an edit to an existing memory is already categorized and never
# changes the count, so it is always silent. Non-blocking text uses
# permissionDecision:allow + additionalContext (the verified channel).
#
# Fail-open: missing jq / bad payload / non-memory path → silent allow.

set -u
command -v jq >/dev/null 2>&1 || exit 0

file="$(cat | jq -r '.tool_input.file_path // empty' 2>/dev/null)"

# Memory files only: <config dir>/projects/<slug>/memory/<name>.md, anchored on the
# harness config dir so a repo folder with the same layout is never mistaken for
# memory. Both sides resolve to physical paths, so a symlinked config dir, a
# trailing slash or a /tmp vs /private/tmp spelling still match. The slug dir is
# resolved rather than memory/, which may not exist before the first memory.
case "$file" in */projects/*/memory/*.md) ;; *) exit 0 ;; esac
memdir="${file%/*}"
[ "${memdir##*/}" = memory ] || exit 0
projects="$(cd "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" 2>/dev/null && pwd -P)" || exit 0
slugdir="$(cd "${memdir%/*}" 2>/dev/null && pwd -P)" || exit 0
[ "${slugdir%/*}" = "$projects" ] || exit 0
# MEMORY.md is the index, not a belief; and an existing file is already routed.
case "${file##*/}" in MEMORY.md) exit 0 ;; esac
[ -e "$file" ] && exit 0

count=0
for f in "$memdir"/*.md; do
  [ -e "$f" ] || continue
  case "${f##*/}" in MEMORY.md) continue ;; esac
  count=$((count + 1))
done
after=$((count + 1))

if [ "$after" -ge 101 ]; then
  reason="MEMORY CAP: this folder already holds $count memories and the cap is 100. A fully new memory needs a slot: propose a stale, duplicate or rule-covered memory for removal or merge (the /reflect prune does this) and wait for the user's approval before deleting anything, then write. Extending an existing memory is always allowed, and is usually the better home."
  jq -n --arg r "$reason" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
  exit 0
fi

read -r -d '' msg <<'EOF'
MEMORY WRITE - route it before you write it. Is this belief:
  (a) specific to THIS repo (its skills, tools, conventions, lifecycles)
        -> memory is correct. Proceed.
  (b) a UNIVERSAL working principle that applies in any repo
        -> belongs in global ~/.claude/CLAUDE.md, NOT repo memory.
  (c) an INVARIANT that must be ENFORCED rather than remembered
        -> belongs in a hook. Prose does not enforce; hooks do.
  (d) a REUSABLE PROCEDURE
        -> belongs in a skill.
  (e) a CLIENT / PROJECT FACT
        -> belongs in that project's own docs (vault, tasks/todo.md).
           NEVER memory: a copy here has no staleness detection and will
           silently contradict the canonical source.
Only (a) proceeds. Name the category before writing.
The MEMORY.md line is the only part loaded every session: say what the memory
holds and when to open it, in under 220 characters, matching its description.
EOF

hygiene="Look for memories that act as hard rules - corrective or prohibitive (\"never\", \"always\"), or applied in most sessions. If a hook already enforces one, the memory is redundant - propose removing it; otherwise it may belong in a path-scoped rule in .claude/rules/ or in a hook."

if [ "$after" -ge 75 ]; then
  msg="$msg

MEMORY COUNT: this write makes $after of a 100 cap. Only add a new memory if it is important and unique; if an existing memory covers the subject, extend that one instead. $hygiene"
elif [ "$after" -ge 50 ]; then
  msg="$msg

MEMORY COUNT: this write makes $after. Time for a hygiene check - run the /reflect prune and look for stale, duplicate or rule-covered memories. $hygiene"
fi

jq -n --arg m "$msg" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow", additionalContext: $m}}'

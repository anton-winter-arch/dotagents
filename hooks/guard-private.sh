#!/usr/bin/env bash
# PreToolUse hook on Bash: refuse any shell command that names ~/.claude/private
# or ~/.claude/state, and any command that places or re-modes a file in
# ~/.claude-mem/bin.
#
# private holds the station's identifier term list and state the gate ack files;
# claude-mem/bin is first on PATH for claude-mem's worker. The file tools are
# denied on all three in settings.json; this closes the shell path (cat, sed,
# python -c, cp). Reads of claude-mem/bin stay allowed. For claude-mem/bin the
# verbs here are half of it: redirects, tee, sed -i, dd and interpreter writes are
# deny-bash-file-writes.sh's, so both hooks stay wired.
# It matches the literal path fragment only, so a command that reaches the folder
# through a variable or a symlink is not caught - this is the honest-case guard,
# not a sandbox. Exit 2 blocks the call. A missing jq denies the call instead
# of letting it run; see _require.sh.

set -uo pipefail
. "$(dirname "$0")/_require.sh" 2>/dev/null || { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"hook preamble missing: _require.sh. This guard cannot evaluate the call, so it refuses."}}\n'; exit 0; }
require_deps jq

CMD="$(jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
[ -n "$CMD" ] || exit 0

case "$CMD" in
  *".claude/private"*)
    echo "blocked: the command names ~/.claude/private, which holds the station's private term list. Its contents are not the model's to read or write; the reject_identifiers hook reads it on its own." >&2
    exit 2
    ;;
  *".claude/state"*)
    # The gate ack files live here. Touching one eases the memory gate or
    # the daemon-storm block for an hour, which is the user's call from a
    # real shell, never an agent's or a seat's.
    echo "blocked: the command names ~/.claude/state, which holds the gate ack files. Easing a gate is the user's decision from their own shell." >&2
    exit 2
    ;;
  *".claude-mem/bin"*)
    # claude-mem puts this folder first on PATH for its worker and every claude it
    # spawns, so a file placed here shadows git, node or claude in those runs.
    # Reading it is fine; placing or re-moding a file is seed.py's job only.
    if printf '%s' "$CMD" | grep -qE '(^|[|&;[:space:]])(cp|mv|install|ln|chmod|chown|touch|rsync|tar|unzip|curl|wget)([[:space:]]|$)'; then
      echo "blocked: the command places or re-modes a file in ~/.claude-mem/bin, which is first on PATH for the claude-mem worker and every claude it spawns. Only the seeded uvx wrapper belongs there, and seed.py writes it." >&2
      exit 2
    fi
    ;;
esac
exit 0

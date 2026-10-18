#!/usr/bin/env bash
# Table-driven tests for the guard-private PreToolUse hook.
# Target: the repo's hooks/guard-private.sh by default; HOOK_UNDER_TEST points the run at
# a station copy such as ~/.claude/hooks/guard-private.sh (per-machine, seeded from
# SPEC-CLAUDE-CODE.md §8). Run: bash tests/station-hooks/test-guard-private.sh
# Exit 0 = all green; nonzero = failures listed.
#
# block = exit 2 (any mention of ~/.claude/private or ~/.claude/state; a placing or
#         re-moding command aimed at ~/.claude-mem/bin)
# pass  = exit 0
set -u

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="${HOOK_UNDER_TEST:-$REPO/hooks/guard-private.sh}"
[ -f "$HOOK" ] || { echo "FATAL: hook not found at $HOOK"; exit 2; }

pass=0; fail=0

check() {
  local expected="$1" label="$2" cmd="$3"
  local got
  jq -cn --arg c "$cmd" '{tool_name:"Bash",tool_input:{command:$c}}' | bash "$HOOK" 2>/dev/null
  [ $? -eq 2 ] && got=block || got=pass
  if [ "$got" = "$expected" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    echo "FAIL [$label] expected=$expected got=$got :: $cmd"
  fi
}

# ---- private and state: any mention blocks ----------------------------------
check block "private-cat"      'cat ~/.claude/private/terms.txt'
check block "private-ls"       'ls ~/.claude/private'
check block "state-touch"      'touch ~/.claude/state/memory-gate-ack'

# ---- claude-mem/bin: placing or re-moding blocks ------------------------------
check block "cmbin-cp"         'cp /tmp/x ~/.claude-mem/bin/git'
check block "cmbin-mv"         'mv ./git "$HOME/.claude-mem/bin/"'
check block "cmbin-chmod"      'chmod +x ~/.claude-mem/bin/git'
check block "cmbin-chained"    'cd /tmp && cp x ~/.claude-mem/bin/node'
check block "cmbin-curl"       'curl -o ~/.claude-mem/bin/claude https://example.invalid/c'
check block "cmbin-ln"         'ln -s /tmp/x ~/.claude-mem/bin/git'

# ---- claude-mem/bin: reads and seeding pass -----------------------------------
check pass  "cmbin-ls"         'ls -l ~/.claude-mem/bin'
check pass  "cmbin-cat"        'cat ~/.claude-mem/bin/uvx'
check pass  "cmbin-run"        '~/.claude-mem/bin/uvx --version'
check pass  "seed-apply"       'python3 ~/.agents/skills/agent-cc-configs-sync/scripts/seed.py apply --harness claude-code --element "claude-mem uvx wrapper"'

# ---- unrelated commands pass ---------------------------------------------------
check pass  "claude-mem-logs"  'tail ~/.claude-mem/logs/claude-mem-2026-10-17.log'
check pass  "plain-cp"         'cp a.txt b.txt'

echo "guard-private: $pass passed, $fail failed"
[ "$fail" -eq 0 ]

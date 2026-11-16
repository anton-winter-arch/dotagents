#!/usr/bin/env bash
# Tone battery for the cmon skill: runs each fixture (a verbose reply) through
# a headless claude with the skill body as the /cmon instruction, and prints
# the distilled restatements for review.
#
# Grading is by eye, not assertion - the criteria, from the skill itself:
#   1. Leads with the point; support limited to what earns its place.
#   2. Full natural sentences - no verbless fragments or telegram style.
#   3. Compressed claims exactly as true as the original.
#   4. No em dashes (known leakage under weak headless models; judge trends,
#      not single runs - measured variance is 0-6 per run at claude-sonnet-5).
#
# Usage: bash tests/cmon-battery/run_battery.sh [model]
#
# Each probe runs under procguard with a 300 s cap. It runs in the background
# and the shell waits on it, because bash defers a trap until a foreground
# child exits; `wait` returns at once, so a signal stops the probe's whole group.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
model="${1:-claude-sonnet-5}"
out="$(mktemp -d)"
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1

guard=""
stop() {
  [ -n "$guard" ] && kill "$guard" 2>/dev/null && wait "$guard"
  echo "stopped; outputs so far in $out" >&2
  exit 130
}
trap stop INT TERM HUP

for f in "$here"/fixtures/f*.md; do
  name="$(basename "$f" .md)"
  {
    echo "The following is the previous exchange in a session:"
    echo
    cat "$f"
    echo
    echo "The user has now invoked /cmon. Its instructions:"
    echo
    sed '1,/^---$/d' "$repo/skills/cmon/SKILL.md"
    echo
    echo "Produce the /cmon response now - only the restatement itself."
  } | python3 "$repo/skills/skill-authoring/scripts/procguard.py" --timeout 300 -- claude -p --model "$model" > "$out/$name.txt" 2>/dev/null &
  guard=$!
  wait "$guard"
  guard=""
  echo "=== $name ($(wc -w < "$out/$name.txt" | tr -d ' ') words)"
  cat "$out/$name.txt"
  echo
done
echo "outputs kept in $out"

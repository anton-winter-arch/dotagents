#!/usr/bin/env bash
# sync-skills.sh - assemble ~/.claude as a per-device VIEW of the synced global set (~/.agents):
#   * skills/   : one leaf symlink per skill dir (a dir containing SKILL.md)
#   * agents/   : one leaf symlink per *.md subagent
#   * commands/ : one leaf symlink per *.md slash command
#   ...alongside any device-local real entries you create directly under ~/.claude.
#
# Source of truth = ~/.agents (sync THIS across computers).
# ~/.claude/{skills,agents,commands} are real, per-device dirs (do NOT sync them).
#
# Idempotent and non-destructive to locals:
#   - never clobbers a real local entry that shares a name with a global
#   - refreshes existing global symlinks (in case a target path changed)
#   - prunes dangling symlinks (globals that were removed upstream)
#
# Usage:  bash ~/.agents/sync-skills.sh [--dry-run]
set -euo pipefail

AGENTS_ROOT="${HOME}/.agents"
CLAUDE_ROOT="${HOME}/.claude"
DRY=""; [ "${1:-}" = "--dry-run" ] && DRY=1

run() { if [ -n "$DRY" ]; then echo "DRY: $*"; else "$@"; fi; }

# Refuse the old parent-level symlink setup (e.g. ~/.claude/skills -> ~/.agents/skills).
assert_real_dir() {
  local d="$1"
  if [ -L "$d" ]; then
    echo "error: $d is a symlink (old parent-level setup)." >&2
    echo "       Convert it first:  rm \"$d\" && mkdir -p \"$d\"" >&2
    echo "       (rm on a symlink removes only the link; the source is untouched.)" >&2
    exit 1
  fi
}

# Prune dangling symlinks (links whose target no longer exists).
prune_dangling() {
  local d="$1"
  [ -d "$d" ] || return 0
  for entry in "$d"/*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    if [ -L "$entry" ] && [ ! -e "$entry" ]; then
      echo "prune dangling : $(basename "$entry")"
      run rm "$entry"
    fi
  done
}

# Resolve the symlink target to write. RELATIVE when the two roots are siblings
# (the normal ~/.agents + ~/.claude layout), so the links carry no absolute path:
# ~/.claude is itself a git repo that tracks these pointers for visibility, and an
# absolute target would bake this machine's home directory into that history and
# clone in dangling on any other. Falls back to absolute if the roots are not
# siblings, where no fixed relative prefix is correct.
rel_target() {
  local src="$1"
  if [ "$(dirname "$AGENTS_ROOT")" = "$(dirname "$CLAUDE_ROOT")" ]; then
    printf '../../%s/%s' "$(basename "$AGENTS_ROOT")" "${src#"$AGENTS_ROOT"/}"
  else
    printf '%s' "$src"
  fi
}

# Create/refresh one leaf symlink, never clobbering a real local entry.
link_one() {
  local src="$1" dest="$2" name target
  name="$(basename "$dest")"; target="$(rel_target "$src")"
  if [ -L "$dest" ]; then
    run ln -sfn "$target" "$dest"; echo "link (refresh): $name"
  elif [ -e "$dest" ]; then
    echo "skip local     : $name (real local entry present - keeping yours)"
  else
    run ln -s "$target" "$dest"; echo "link global    : $name"
  fi
}

# Link each global SKILL dir (a dir containing SKILL.md), preserving local overrides.
sync_skill_dirs() {
  local global="$1" local_dir="$2"
  [ -d "$global" ] || { echo "(no $global - skipping)"; return 0; }
  assert_real_dir "$local_dir"
  run mkdir -p "$local_dir"
  prune_dangling "$local_dir"
  for src in "$global"/*/; do
    src="${src%/}"
    [ -f "$src/SKILL.md" ] || continue          # only real skills
    link_one "$src" "$local_dir/$(basename "$src")"
  done
}

# Link each global *.md file (subagents, commands), preserving local overrides.
sync_md_files() {
  local global="$1" local_dir="$2"
  [ -d "$global" ] || { echo "(no $global - skipping)"; return 0; }
  assert_real_dir "$local_dir"
  run mkdir -p "$local_dir"
  prune_dangling "$local_dir"
  for src in "$global"/*.md; do
    [ -f "$src" ] || continue                   # tolerate empty dir
    link_one "$src" "$local_dir/$(basename "$src")"
  done
}

[ -d "$AGENTS_ROOT/skills" ] || { echo "error: $AGENTS_ROOT/skills not found (is your global set synced here?)" >&2; exit 1; }

echo "== skills =="
sync_skill_dirs "$AGENTS_ROOT/skills"   "$CLAUDE_ROOT/skills"
echo "== agents =="
sync_md_files   "$AGENTS_ROOT/agents"   "$CLAUDE_ROOT/agents"
echo "== commands =="
sync_md_files   "$AGENTS_ROOT/commands" "$CLAUDE_ROOT/commands"

echo "done. ~/.claude/{skills,agents,commands} now mix global symlinks + local real entries."

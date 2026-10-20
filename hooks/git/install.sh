#!/bin/sh
# Point git's global core.hooksPath at the station dispatcher in this folder, or take it away.
#
#   sh hooks/git/install.sh              show the current value, then set it
#   sh hooks/git/install.sh --force      replace a different existing value
#   sh hooks/git/install.sh --uninstall  remove it, only when it points here
#   sh hooks/git/install.sh --check      print the current value and whether it points here
#
# A global hooks path changes every repo on the station: each repo's own .git/hooks still
# runs, through the dispatcher's chain, but a repo that sets its own core.hooksPath (husky,
# lefthook) keeps it and the content check does not run there.
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
current=$(git config --global --get core.hooksPath 2>/dev/null || true)
case "$current" in
  "~/"*) resolved="$HOME/${current#"~/"}" ;;
  *) resolved="$current" ;;
esac
if [ -n "$resolved" ] && [ -d "$resolved" ]; then
  resolved=$(cd "$resolved" && pwd -P)
fi

case "${1:-}" in
  --check)
    if [ "$resolved" = "$here" ]; then
      echo "core.hooksPath: installed ($here)"
    else
      echo "core.hooksPath: ${current:-unset} (not the station dispatcher)"
      exit 1
    fi
    exit 0
    ;;
  --uninstall)
    if [ "$resolved" = "$here" ]; then
      git config --global --unset core.hooksPath
      echo "core.hooksPath removed"
    else
      echo "core.hooksPath is ${current:-unset}, not the station dispatcher; left alone"
    fi
    exit 0
    ;;
  ""|--force) ;;
  *)
    echo "usage: sh $0 [--force | --uninstall | --check]" >&2
    exit 2
    ;;
esac

echo "core.hooksPath now: ${current:-unset}"
if [ "$resolved" = "$here" ]; then
  echo "already installed"
  exit 0
fi
if [ -n "$current" ] && [ "${1:-}" != "--force" ]; then
  echo "refusing to replace an existing global hooks path; rerun with --force to replace it" >&2
  exit 1
fi
if [ ! -x "$here/dispatch" ] || [ ! -L "$here/pre-commit" ]; then
  echo "the dispatcher or its hook links are missing from $here; nothing changed" >&2
  exit 1
fi
git config --global core.hooksPath "$here"
echo "core.hooksPath set: $here"

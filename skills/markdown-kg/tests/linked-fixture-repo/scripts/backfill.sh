#!/usr/bin/env bash
# Re-run the daily report for every readings file in a folder.
set -euo pipefail

for f in "$1"/*.csv; do
  python3 src/tidelog/cli.py "$f"
done

#!/usr/bin/env bash
# Nightly report. The console script resolves the report module at run time.
set -euo pipefail
greenhouse report "$@"

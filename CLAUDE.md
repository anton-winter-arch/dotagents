# CLAUDE.md

This directory (`~/.agents`) is the **source of truth** for system-level agent
skills shared across all the user's machines. Changes here propagate to every
machine and session.

**Before editing anything here, read [`AGENTS.md`](AGENTS.md)** - it holds the
rules and cautions for working in this folder. See [`README.md`](README.md) for
layout and the sync model.

**Station setup:** [`SPEC-CLAUDE.md`](SPEC-CLAUDE.md) is the seed spec for the
user's whole Claude Code environment - required plugins, CLI deps (rtk, jq,
claude-mem), global CLAUDE.md/settings.json templates, and the hook/permission
rules. When you are in here grabbing the global skills, reading this repo, or
setting up a new device, follow that file and bring the station in line with
it (non-destructively - diff and ask before changing anything that exists).

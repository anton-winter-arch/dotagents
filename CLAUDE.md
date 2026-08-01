# CLAUDE.md

This directory (`~/.agents`) is the **source of truth** for the agent skills,
subagents, commands and harness configs shared across every machine. Changes
here propagate to every machine and session.

**Before editing anything here, read [`AGENTS.md`](AGENTS.md)** - it holds the
rules and cautions for working in this folder. See [`README.md`](README.md) for
layout and the sync model.

**Station setup:** [`specs/`](specs/) holds one long-lived spec per harness -
what a machine's install of that harness needs configured around these skills.
[`specs/SPEC-CLAUDE.md`](specs/SPEC-CLAUDE.md) is by far the fullest: required
plugins, CLI deps (rtk, jq, claude-mem), the global `CLAUDE.md`/`settings.json`
templates, and the hook and permission rules. When setting up a new device or
working in here, follow the spec for the harness in use and bring the station in
line with it - non-destructively, diffing and asking before changing anything
that already exists.

# Why the checklist asks what it asks

Background for `../SKILL.md`. The checks live there; this file explains them and maps
their coverage. Nothing here adds a check.

## Scope

The checklist is a gate for agent tooling: skills, subagents, slash commands, hooks,
shell and sync scripts, dotfiles, and plugin/MCP configuration. Web-app security is
`agent-skills:security-and-hardening`. Agent tooling has its own attack surface:
arbitrary command execution via hooks, untrusted LLM/agent output flowing into actions,
secrets sitting in config files, and destructive file operations on a synced source of
truth.

It is a pre-push ritual, not an audit. It runs several times a day, so its scope is the
files the session changed, read against every domain, plus the whole folder of any skill
or hook that did not exist before. The standards do not relax with the scope: a changed
line gets the full checklist. Sweeping the rest of the repository is a separate job the
user asks for by name, and a reviewer that drifts into it reports late on a tree that has
already moved.

## 4a. Hidden characters

Reviewing a diff is reviewing rendered text, but the model reads codepoints. Characters
that render as nothing, or that reorder the display without reordering the bytes, let an
attacker put one instruction on the screen and a different one in the agent's context.
The reviewer approves what they saw. This applies to every file an agent reads as
instructions - skills, subagents, commands, rules, hooks, settings, inbox messages - and to
anything pasted in from a web page, an issue, or another agent.

## 7a. Network exposure

Local model servers, MCP servers over HTTP, dev servers and debug endpoints are almost
always unauthenticated. They assume they are unreachable, and a bind address is the only
thing enforcing that. Moving one off loopback publishes an open endpoint to every device
on the network, and on a cafe or hotel LAN, to strangers.

## 7b. Egress and persistence

Sections 4 and 4a cover what comes in. 7b covers what leaves, and what survives after a
review passes. Both are how a single bad skill becomes an ongoing problem rather than a
one-off.

## 8. Portability and personal constants

A shared source of truth syncs to every machine and every user context, so a path that
only resolves on the author's machine is a defect: it silently breaks on another device
and can leak the username into git history. The rule generalizes beyond paths: no
hardcoded personal fact the agent cannot infer at runtime. Anything personal - username,
real name, email, GitHub handle or repo URL, vault or project names, hostnames - is
discovered live (session context, env vars, `$HOME`, `git config`/`git remote`, workspace
metadata) or asked of the user in real time.

## 9. The multi-agent surface

Sections 1-8 review one agent editing files. The section 9 risks only exist once work fans
out across agents, sessions or repos, and none of them are visible in a single diff: each
needs a question asked of the arrangement, not the change.

## Mapping to the OWASP Top 10 for Agentic Applications 2026

Published 2025-12-09; that is the artifact's real name, and "OWASP Agentic Top 10" is a
colloquial contraction that matches no OWASP document. The table keeps a coverage claim
checkable; the checklist stays organized by artifact, because that is how a review runs.

| OWASP | Covered by |
|---|---|
| ASI01 Agent Goal Hijack | §4, §4a |
| ASI02 Tool Misuse | §3, §7 |
| ASI03 Identity & Privilege Abuse | §1, §7 - thin by design: a single-operator station has one principal |
| ASI04 Agentic Supply Chain | §5 - **plugin and MCP install trust only.** Whether a catalog or corpus entry understates a license or reads as an endorsement to install is not covered by any section; that discipline is convention, not a gate |
| ASI05 Unexpected Code Execution | §2, §3 |
| ASI06 Memory & Context Poisoning | §9 |
| ASI07 Insecure Inter-Agent Communication | §9 |
| ASI08 Cascading Failures | §9 - parallel fan-out only; sequential retry storms and escalation loops are uncovered |
| ASI09 Human-Agent Trust Exploitation | §4a |
| ASI10 Rogue Agents | §9 |

## Red flags at a glance

Each of these is a check in `../SKILL.md`, listed here for a fast skim:

- A hook or script that builds a command string from untrusted content
- `rm -rf "$VAR/..."` where `$VAR` could be empty or attacker-influenced
- Secrets, tokens, or `.env` contents in a staged diff
- `0.0.0.0`, `::`, or `OLLAMA_HOST` set to anything routable
- Installing a plugin/MCP server from an unverified or look-alike source
- Untrusted agent/web/MCP output being executed or obeyed as an instruction
- Any invisible or display-reordering character in a file an agent reads as instructions
- Destructive file ops on `~/.agents` or `~/.claude` with no archive/git safety net
- Wildcard permission grants in `settings.json`
- A username-bearing absolute path, or a global tool hardcoded to one vault or device
- A hardcoded personal fact the agent could infer or ask for
- A memory, rules, or skill file edited from content an agent returned
- A write-capable fan-out with no ceiling, or one where two workers can write the same file

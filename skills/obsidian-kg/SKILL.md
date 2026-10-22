---
name: obsidian-kg
description: Renamed to markdown-kg. This entry only forwards there and loads nothing else.
disable-model-invocation: true
---

# obsidian-kg (renamed)

This skill is now `skills/markdown-kg/`.
The engine and its commands are unchanged; the skill name, the script name and the engine's folder inside a vault moved.
Use `python3 <skills-root>/markdown-kg/scripts/markdown_kg.py`.
The engine's folder inside a vault is now `markdown-kg/`, and an existing `vault-kg/` folder keeps working in place.

`scripts/obsidian_kg.py` here is a forwarder: it runs the new engine with the
same arguments and prints one notice to stderr, so an old command line keeps
working until its caller is updated.

If `~/.claude/skills/markdown-kg` is missing on a machine, run
`bash ~/.agents/sync-skills.sh`.

This pointer is removed once no live caller names the old path.

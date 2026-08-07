# CLAUDE.md

`~/.agents` is the **source of truth** for the agent skills, subagents, commands
and harness configs shared across every machine. A change here reaches every
machine and every future session.

- **Before editing anything here, read [`AGENTS.md`](AGENTS.md)** - the rules,
  and the cautions specific to this repo.
- [`README.md`](README.md) - layout and the sync model.
- [`specs/`](specs/) - one long-lived station spec per harness, stating what a
  machine's install of that harness needs configured around these skills.
  [`SPEC-CLAUDE.md`](specs/SPEC-CLAUDE.md) is the fullest. Follow the spec for
  the harness in use and bring the station in line with it non-destructively,
  diffing and asking before changing anything that already exists.

The rules file that seeds a machine's global `~/.claude/CLAUDE.md` is
[`specs/claude-code/CLAUDE.md.example`](specs/claude-code/CLAUDE.md.example).
The other station templates sit beside it, indexed in §0 of the spec.

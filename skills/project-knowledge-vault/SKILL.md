---
name: project-knowledge-vault
description: >-
  Seeds and checks a project knowledge vault - one flat folder of markdown notes a project's people and agents share as its source of truth, read through markdown-kg as its own graph once it outgrows a single read. Owns the contract (AGENTS.md), the seed files, a scaffolder that also seeds the graph, and a linter. Use when starting a vault or a new project under PROJECTS/, when asked to set up, seed, scaffold or template a project's notes, when checking whether a vault conforms or why the graph or board tools read it badly, when a vault has grown too long to read whole, or when a project needs a home for its meetings, chat, learnings, questions and stories. The knowledge base and research flows belong to their own skills; so do the board (sprint-board) and graph queries (markdown-kg).
---

# project-knowledge-vault

A project vault is the hub object of a knowledge stack. It is one flat directory, and the filename prefix is the category: `00-brd` states the why, `01-north-star` says who the vault serves and who is who, `notes-*` capture what happened, `notes-learnings` holds what turned out to be true, `notes-questions` is the one register of open questions, and `user-stories*` hold the work, its run sheet, its backlog and its research. `index.md` and `log.md` are the OKF front door and change history. The full contract is `templates/PROJECTS/AGENTS.md`, and that file ships into every vault, so the contract has exactly one copy.

The seed follows the shape of the most worked-in project vaults: chat split into client and internal files, a month H1 and jump link per month in every dated file, an UPCOMING block in the meeting notes, learnings sweeps with a one-line headline, story-keyed PR reviews, a START HERE run sheet, and an alias roster in the north-star.

## Commands

```
seed      python3 scripts/vault_scaffold.py --target <path> --name <NAME> [--dry-run] [--no-graph]
lint      python3 scripts/vault_lint.py <path>/PROJECTS/<NAME> [--json]
test      python3 -m pytest tests -q
```

The scaffolder writes `<path>/PROJECTS/<NAME>/` from `templates/PROJECTS/`. It never overwrites: an existing file is reported as skipped, so a run against a part-built vault fills the gaps. It resolves no dates, so two runs on different days produce byte-identical notes. Then it seeds the graph: it runs markdown-kg's `init` when the vault has no graph config, merges any row from `templates/markdown-kg-profiles.md` that the config lacks, and ingests when a note or a row was added. markdown-kg is found beside this skill; when it is absent the step is reported and skipped. Exit 1 means a file could be neither written nor skipped, or the graph step failed.

The linter is the anti-drift mechanism. Every check fires on positive evidence, and an unreadable file is a failure rather than a pass. Exit 0 clean, 1 on any finding.

| check | fails on |
|---|---|
| `flat` | any subdirectory other than `markdown-kg/`, the legacy `vault-kg/` or a dot-folder |
| `frontmatter` | a note without parseable YAML carrying a non-empty `type` |
| `family` | a `type` outside the family table for that prefix, or a prefix in no family |
| `reserved` | `index.md` or `log.md` missing, or any frontmatter on either |
| `filename` | anything not lowercase-kebab |
| `wikilink` | a `[[target]]` with no note in the vault |
| `anchor` | a `[[note#Heading]]` whose heading does not exist |
| `dated` | a `notes-*` H2 that is not `YYYY-MM-DD-...`, `YYYY-MM-DD - <headline>`, `PREP: ...`, `About this file` or `Related`, or in `notes-pr-reviews.md` `PR-STORY-...`; `log.md` H2s not ISO and newest first |
| `board` | `user-stories.md` restating sprint-board's grammar instead of pointing at it |
| `placeholder` | a literal `YYYY-MM-DD` in a hand-written note that already carries real dates |

`AGENTS.md` and `CLAUDE.md` are the contract, not notes. `code-*` and `docs-*` are ingested byte-for-byte and are exempt from the placeholder check. `notes-questions.md` is a register grouped by topic, not dated capture. Text inside fences, inline code and HTML comments is invisible to every check, which is why each seed file keeps its entry format in a fenced block.

## Reading a vault as it grows

A vault is append-only by design, so its `notes-*` files grow without bound, and within months reading one whole costs more context than the answer is worth. markdown-kg is how a grown vault is read, and the contract tells every agent in the vault so. The seed is built for it: one idea per heading so each is addressable, a date in every dated heading so recency ranking and `timeline` work, the `**SUPERSEDED**` marker so stale sections rank below their replacements, and month H1s that the engine treats as grouping while each dated H2 stays its own section.

- **Point queries at the graph root.** That is the vault itself after a seed, or the build output where a pipeline builds the vault into another folder. A raw folder that a build reads has no graph of its own.
- **The loop** is `search` for ranked sections, `read` for one section whole, `sections` for a note's map, and `ingest` after writing. The query commands and their flags belong to markdown-kg's own skill.
- **One graph per vault.** Every project vault has the same reserved filenames, so a graph over all of `PROJECTS/` would find every bare wikilink ambiguous; a parent vault's own graph ignores `PROJECTS/**` in its `.kgignore`. The engine's `index` command writes `Vault Index.md` and never `index.md`.

## Where it sits in the stack

- **markdown-kg** reads each vault as its own graph root, through the config rows this skill ships and merges. This skill shapes notes for the engine; it never teaches the engine the contract.
- **sprint-board** owns `user-stories.md` and `user-stories-completed.md`. The seed ships the board empty; write the spine as JSON, run its `board_scaffold.py`, and append the output after the seed's preamble. A fresh scaffold reports template residue until the bodies are written, and that is the author's job, not the vault's. The run sheet, backlog and research files are the vault's own working files, not boards.
- **The knowledge base, learning path and certification flow** live outside the vault. A project pushes durable facts up through `notes-learnings.md` for the certification flow to promote, and declares what it needs in the `skills:` list on `00-brd.md`, which a knowledge base diffs against its proven skills to find the gap and seed the learning path.
- **okf-vault** (a build pipeline in another repo) produces a vault of this shape from raw sources. The relationship is a conformance check, not a dependency: point `OKF_VAULT_BUILD` at a build output and the test suite lints it.

## Boundaries

**Always** lint a vault before calling a change to it done. Repoint every inbound link in the same commit as a rename. Keep the contract to one copy.

**Ask first** before adding a second template profile, changing a family name or `type` value (every existing vault stops conforming), or resolving a real date into a template file.

**Never** teach markdown-kg the contract, restate sprint-board's anatomy in the seed, use a `kg-` frontmatter key, or put an identifier in anything under `templates/`. The templates ship into public repos and git history keeps what a later cleanup removes.

## Files

- `templates/PROJECTS/` - the 19 seed files, including the contract
- `templates/markdown-kg-profiles.md` - the graph config rows the scaffolder merges
- `scripts/vault_scaffold.py`, `scripts/vault_lint.py`
- `tests/` - scaffold and graph seeding, one adversarial fixture per linter check, and the compatibility tests against sprint-board and markdown-kg

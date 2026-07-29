---
name: obsidian-kg
description: Builds and queries a SQLite+FTS5 knowledge graph over an Obsidian vault - wikilinks ([[Note]], [[Note|alias]], [[Note#heading]]), embeds (![[...]]), frontmatter properties/aliases/tags, and standard markdown links. Use when asked to index, search, query, or traverse an Obsidian vault - e.g. "make this vault queryable", "search the vault for X", "what links to note Y", "backlinks for Z", "how are these notes connected" - when answering any factual question from a wikilink vault's contents, when diagnosing link problems an ingest reported ("ambiguous links", "two notes with the same name", "unresolved link"), or when any agent needs ranked search or the link graph of a wikilink vault instead of raw grep. Fully offline and deterministic - no API keys, no network. The graph lives at <vault>/.obsidian-kg.db and rebuilds idempotently from the markdown. For OKF vaults (standard-md-link concept notes) use okf-kg instead.
---

# obsidian-kg

Turn an Obsidian vault into a queryable SQLite knowledge graph, then answer
from it. Twin of `okf-kg`, tuned for Obsidian semantics. One engine, no
dependencies beyond Python 3.10+ stdlib: EXECUTE `scripts/obsidian_kg.py`
via Bash for every operation - never reimplement its parsing or query logic
inline.

An Obsidian vault is any directory of markdown notes joined by wikilinks
(a `.obsidian/` dir is the usual marker but is not required). The engine
parses both link syntaxes Obsidian accepts - `[[wikilinks]]` in all forms
(alias, `#heading`, `![[embed]]`) and standard `[text](target.md)` links -
plus YAML frontmatter (tags, `aliases:`, and other scalar properties).
Links inside code fences and inline code are ignored. The vault path is
always an argument - this skill works on any vault on disk.

## Workflow

1. **Ingest first, always.** Cheap, idempotent, full-rebuild - safe to run
   at the start of every session that touches the vault, and again after
   any edit:

   ```bash
   python3 <skill-dir>/scripts/obsidian_kg.py ingest <vault-dir>
   ```

   The DB lands at `<vault>/.obsidian-kg.db` - gitignore it in the target
   vault; it rebuilds from markdown at any time. Ingest reports note and
   edge counts plus unresolved and ambiguous link counts.

2. **Query to locate, then read the source files.** The graph is for
   *finding* the right two or three notes, not a substitute for reading
   them:

   ```bash
   python3 <skill-dir>/scripts/obsidian_kg.py query <vault-dir> '"spaced repetition"'
   python3 <skill-dir>/scripts/obsidian_kg.py query <vault-dir> 'zettel AND inbox'
   ```

   FTS5 syntax: bare terms ANDed, quoted phrases, `OR`/`NOT`, `*` prefix
   match. Results are bm25-ranked with snippets.

3. **Traverse the link graph.** Notes resolve by basename or frontmatter
   alias, case-insensitive, the way Obsidian resolves `[[links]]`:

   ```bash
   python3 <skill-dir>/scripts/obsidian_kg.py backlinks <vault-dir> "Some Note"
   python3 <skill-dir>/scripts/obsidian_kg.py links <vault-dir> "Some Note"
   python3 <skill-dir>/scripts/obsidian_kg.py neighbors <vault-dir> "Some Note" --depth 2
   python3 <skill-dir>/scripts/obsidian_kg.py path <vault-dir> "Note A" "Note B"
   ```

   Edges carry `syntax` (`wiki`/`md`) and `kind` (`link`/`embed`).

4. **Orient with tags and stats:**

   ```bash
   python3 <skill-dir>/scripts/obsidian_kg.py tags <vault-dir>
   python3 <skill-dir>/scripts/obsidian_kg.py stats <vault-dir>
   ```

   `stats` reports orphans, edge breakdown by syntax/kind, and unresolved
   and ambiguous links (with examples) - ambiguity means a bare `[[link]]`
   matched multiple basenames; the engine records it rather than guessing.

## Conventions

- Read the underlying `.md` before asserting facts from a snippet.
- Re-ingest after edits; queries against a stale db mislead silently.
- Basename collisions: link with a path fragment (`[[folder/Note]]`) to
  disambiguate; bare ambiguous links are surfaced in `stats`.
- Exit code is nonzero on errors, on missing db (run `ingest` first), and
  on `path` with no connection.

## When NOT to use

- Not for OKF vaults - frontmattered concept notes joined by standard
  markdown links belong to `okf-kg` (strict md-link edges by design).
- Not a document store or editor - it never writes to vault markdown.
- Not for authoring or formatting Obsidian notes - that is the `obsidian`
  skill. This one only indexes and queries.
- No embeddings/semantic layer yet - deferred by design; FTS5 keyword
  search only. Nothing in this skill calls any API.

## Files

- `scripts/obsidian_kg.py` - the whole engine (EXECUTE; stdlib only).
- `references/schema.md` - DB schema reference (READ when writing raw SQL
  against `.obsidian-kg.db`).
- `tests/` - fixture vault + unit/idempotency tests
  (`python3 -m unittest discover skills/obsidian-kg/tests`).

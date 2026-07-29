---
name: okf-kg
description: Builds and queries a SQLite+FTS5 knowledge graph over an OKF markdown vault (a curated knowledge base of frontmattered concept notes joined by standard markdown links). Use when asked to ingest, index, search, query, or traverse an OKF vault or knowledge base - e.g. "ingest this vault", "search the knowledge base for X", "what links to concept Y", "how are A and B connected", "rebuild the knowledge graph" - when answering ANY factual or relationship question from such a vault's contents ("using the vault at <path>, what/how..."; "what does the knowledge base say about X") - or when any agent needs to orient inside a vault of concept notes before answering from it or generating docs. Fully offline and deterministic - no API keys, no network. The graph lives at <vault>/.okf-kg.db and rebuilds idempotently from the markdown.
---

# okf-kg

Turn an OKF markdown vault into a queryable SQLite knowledge graph, then
answer from it. One engine, no dependencies beyond Python 3.10+ stdlib:
EXECUTE `scripts/okf_kg.py` via Bash for every operation - never reimplement
its parsing or query logic inline.

An OKF vault is a directory of markdown concept notes (usually under
`knowledge-base/`, plus an `index.md` hub and a `log.md`) with YAML
frontmatter (`type`, `title`, `description`, `tags`, `timestamp`, `source`)
and standard markdown links between notes. The vault path is always an
argument - this skill works on any OKF vault on disk.

## Workflow

1. **Ingest first, always.** Cheap and idempotent - safe to run at the start
   of every session that touches the vault:

   ```bash
   python3 <skill-dir>/scripts/okf_kg.py ingest <vault-dir>
   ```

   Reports added / updated / removed / unchanged. A second run on an
   unchanged vault reports zero changes. Deleted files go `cold` (kept with
   provenance), never deleted. The DB lands at `<vault>/.okf-kg.db` -
   gitignore it in the target vault; it rebuilds from markdown at any time.

2. **Query to locate, then read the source files.** Concept notes are a few
   KB - the graph is for *finding* the right two or three notes, not a
   substitute for reading them:

   ```bash
   python3 <skill-dir>/scripts/okf_kg.py query <vault-dir> '"silver layer"'
   python3 <skill-dir>/scripts/okf_kg.py query <vault-dir> 'governance AND ownership'
   ```

   The query string is FTS5 syntax: bare terms are ANDed, quote phrases,
   `OR`/`NOT` work, `*` suffix for prefix match. Results are bm25-ranked
   with snippets and include each hit's concept id.

3. **Traverse to build context.** Concept ids are vault-relative paths
   without `.md` (e.g. `knowledge-base/decisions-foo`):

   ```bash
   python3 <skill-dir>/scripts/okf_kg.py neighbors <vault-dir> <concept-id> --depth 2
   python3 <skill-dir>/scripts/okf_kg.py path <vault-dir> <id-a> <id-b>
   ```

   `neighbors` BFSes the link graph in both directions (`--kind` restricts
   edge kind); `path` returns the shortest chain connecting two concepts -
   useful for explaining how two topics relate.

4. **Re-ingest after edits.** Any time vault files change, run `ingest`
   again before querying; only changed files are reprocessed.

## Conventions

- Cite concepts by id and read the underlying `.md` before asserting facts
  from a snippet.
- `index.md` is a hub node linked to everything; for meaningful neighbors of
  a concept, its non-index neighbors carry the signal.
- Exit code is nonzero on errors and on `path` with no connection; unknown
  concept ids fail with a hint to use `query`.

## When NOT to use

- Not for generic (non-OKF) markdown folders or Obsidian vaults using
  wikilinks - edges come from standard `[text](target.md)` links only.
  Wikilink vaults belong to the `obsidian-kg` twin skill.
- Not a document store or editor - it never writes to vault markdown.
- No LLM enrichment or conflict adjudication yet: `enrich` (quote-verified
  entity/relation extraction) and `conflicts` (hot/cold contradiction
  ledger) are deferred by design; the schema reserves their tables so
  adding them later needs no migration. Nothing in this skill calls any
  API.

## Files

- `scripts/okf_kg.py` - the whole engine (EXECUTE; stdlib only).
- `references/schema.md` - DB schema reference (READ when writing raw SQL
  against `.okf-kg.db`).
- `tests/` - fixture vault + unit/idempotency tests
  (`python3 -m unittest discover skills/okf-kg/tests`).

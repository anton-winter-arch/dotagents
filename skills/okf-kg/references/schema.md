# .okf-kg.db schema reference

SQLite database created by `okf_kg.py` at `<vault>/.okf-kg.db`. Read this
before writing raw SQL against the DB; prefer the CLI subcommands otherwise.

## Contents

- [concepts](#concepts)
- [edges](#edges)
- [extractions / conflicts (reserved)](#extractions--conflicts-reserved)
- [Full-text indexes](#full-text-indexes)
- [Conventions](#conventions)

## concepts

One row per markdown file in the vault.

| column | meaning |
|---|---|
| `id` | vault-relative path without `.md` (primary key), e.g. `knowledge-base/foo` |
| `path` | vault-relative path with `.md` |
| `title` | frontmatter `title`, else first `# heading`, else filename stem |
| `type` | frontmatter `type` (e.g. `decision`, `runbook`), may be empty |
| `description` | frontmatter `description` |
| `tags` | comma-joined frontmatter `tags` |
| `source` | frontmatter `source` |
| `doc_timestamp` | the source's own timestamp: `timestamp`, else `last-modified`, else `date-created` |
| `content_hash` | sha256 of the raw file text (idempotency key) |
| `body` | raw file text (offset base for future quote grounding) |
| `observed_at` | UTC ISO time this row was last written by ingest |
| `status` | `hot` (file present) or `cold` (file deleted from disk) |

## edges

Directed links between concepts. Primary key `(src, dst, kind)`.

| column | meaning |
|---|---|
| `src`, `dst` | concept ids |
| `kind` | `link` for deterministic markdown-link edges (other kinds reserved for future extraction) |
| `quote`, `q_start`, `q_end` | reserved for extracted edges (empty/NULL on `link` edges) |
| `observed_at` | UTC ISO time written |
| `status` | `hot` or `cold` (edges go cold when either endpoint's file is deleted) |

Only internal `.md` targets that resolve inside the vault become edges;
external URLs, non-markdown targets, and dangling links are skipped
(dangling links are counted in the ingest report).

## extractions / conflicts (reserved)

Created empty by the schema for the deferred `enrich` and `conflicts`
features (LLM extraction and contradiction ledger, deferred by design).
No code writes to them yet; `query`
already unions `extractions_fts` so enriched facts will surface without a
schema migration.

## Full-text indexes

- `concepts_fts` - FTS5 external-content table over `(title, description,
  tags, body)`, kept in sync by triggers on `concepts`.
- `extractions_fts` - same pattern over `(subject, predicate, object,
  quote)` for the reserved extractions table.

Query with `MATCH` and rank with `bm25(...)`; the CLI's `query` subcommand
does this and filters to `status='hot'`.

## Conventions

- All timestamps are UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).
- Nothing is ever deleted by ingest; rows flip to `cold` and flip back to
  `hot` (as an update) if the file reappears.
- The DB is disposable: delete it and re-run `ingest` for a clean rebuild.

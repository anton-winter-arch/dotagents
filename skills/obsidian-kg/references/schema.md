# .obsidian-kg.db schema reference

SQLite database created by `obsidian_kg.py` at `<vault>/.obsidian-kg.db`. Read
this before writing raw SQL against the DB; prefer the CLI subcommands
otherwise.

## Contents

- [notes](#notes)
- [properties](#properties)
- [tags / aliases](#tags--aliases)
- [edges](#edges)
- [meta](#meta)
- [Full-text index](#full-text-index)
- [Conventions](#conventions)

## notes

One row per markdown file in the vault (dot folders - `.obsidian`, `.git`,
`.trash`, … - and `SKIP_FOLDERS` are never ingested; in a git repo the file
set has gitignore parity via `git ls-files --cached --others
--exclude-standard`).

| column | meaning |
|---|---|
| `id` | vault-relative path without `.md` (primary key), e.g. `plans/Garden Plan` |
| `path` | vault-relative path with `.md` |
| `title` | frontmatter `title`, else first `# heading`, else filename stem |
| `tags` | comma-joined frontmatter tags (denormalized for FTS; canonical set in `tags`) |
| `aliases` | comma-joined frontmatter aliases (canonical set in `aliases`) |
| `content_hash` | sha256 of the raw file text |
| `body` | raw file text |

## properties

Every frontmatter key/value except `tags` and `aliases` (those get their own
tables). One row per key; list values are stored comma-joined.

| column | meaning |
|---|---|
| `note_id` | `notes.id` |
| `key` | frontmatter key as written |
| `value` | scalar value as a string (lists comma-joined) |

## tags / aliases

Normalized frontmatter `tags:` and `aliases:`, one row per value. Leading `#`
is stripped from tags; case is preserved as written, and lookups (`tags`
command, wikilink alias resolution) are case-insensitive.

| column | meaning |
|---|---|
| `note_id` | `notes.id` |
| `tag` / `alias` | the value as written |

## edges

One row per distinct link occurrence, extracted fence-aware (fenced code
blocks and inline code never become edges). Primary key
`(src, syntax, kind, target)` - repeat links to the same target from one note
collapse to one row.

| column | meaning |
|---|---|
| `src` | source note id |
| `dst` | resolved note id, or NULL when `status` is `unresolved`/`ambiguous` |
| `target` | the link target as written, minus `#heading` and `\|alias` parts (md targets are URL-decoded) |
| `syntax` | `wiki` (`[[...]]`) or `md` (`[text](target.md)`) |
| `kind` | `link`, or `embed` for `![[...]]` transclusions |
| `status` | `resolved`, `unresolved` (no such note), or `ambiguous` (basename collision, never guessed) |

Resolution rules (mirror Obsidian):

- wikilinks resolve vault-wide by case-insensitive basename, then by
  frontmatter alias; a path fragment in the target (`[[projects/Note]]`)
  disambiguates by case-insensitive path suffix (shortest-unique-path);
  a bare name whose basename collides is recorded `ambiguous` with `dst`
  NULL - the engine never guesses.
- markdown links resolve as relative paths from the source file (or
  vault-root paths when leading `/`); only internal `.md` targets become
  edges - external URLs and asset targets (images, pdf, …) are skipped and
  counted in the ingest report.

Graph traversal (`neighbors`, `path`) runs undirected over `resolved` edges
only.

## meta

Single `ingested_at` row (UTC ISO-8601) - the **only** non-deterministic
content in the file. Everything else is a pure function of the vault bytes.

## Full-text index

- `notes_fts` - FTS5 external-content table over `(title, tags, aliases,
  body)`, rebuilt wholesale (`INSERT INTO notes_fts(notes_fts) VALUES
  ('rebuild')`) at the end of each ingest.

Query with `MATCH` and rank with `bm25(...)`; the CLI's `query` subcommand
does this.

## Conventions

- `ingest` is an idempotent **full rebuild**: every table is wiped and
  re-populated in sorted file order, so the same vault bytes always produce
  the same rows (row counts and content are stable across re-runs).
- The DB is disposable: delete it and re-run `ingest` for a clean rebuild.
- Query commands (`query`, `note`, `backlinks`, `links`, `neighbors`, `path`,
  `tags`, `stats`) exit nonzero with a "run `ingest`" message when the DB is
  missing.

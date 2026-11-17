# markdown-kg.db schema reference

`markdown_kg.py` creates the SQLite database at `<vault>/.kg/markdown-kg.db`, beside `markdown-kg-config.json`.
A vault not yet migrated has it at the legacy `markdown-kg/markdown-kg.db` or `vault-kg/vault-kg.db`, and the engine keeps using that file in place.
Read this before writing raw SQL against the DB; prefer the CLI subcommands otherwise.
When code-kg has indexed the same root, its `code-kg.db` sits in the same `.kg/`, and one connection can read both: `ATTACH '.kg/code-kg.db' AS code` names its tables `code.<table>`.

## Contents

- [notes](#notes)
- [sections](#sections)
- [properties](#properties)
- [tags / aliases](#tags--aliases)
- [edges](#edges)
- [anchors](#anchors)
- [link_fields](#link_fields)
- [inline_tags](#inline_tags)
- [file_links](#file_links)
- [code_spans](#code_spans)
- [members](#members)
- [entities / entity_aliases / mentions](#entities--entity_aliases--mentions)
- [ignored](#ignored)
- [other_files](#other_files)
- [annotations / annotation_candidates](#annotations--annotation_candidates)
- [extractions / conflicts](#extractions--conflicts)
- [session_reads](#session_reads)
- [meta](#meta)
- [Full-text index](#full-text-index)
- [Conventions](#conventions)

## notes

One row per ingested markdown file.
Dot folders such as `.obsidian`, `.git` and `.trash`, the folders in `SKIP_FOLDERS` and the engine's legacy folders (`markdown-kg/` and `vault-kg/`) are never ingested; `.kg/` is a dot folder.
Enumeration is a filesystem walk that applies the `.kgignore` files at or
below the vault root and never git, so gitignored notes and notes inside a
nested git repo are ingested like any other. Files excluded by an ignore rule
are not here at all; see [ignored](#ignored).

| column | meaning |
|---|---|
| `id` | vault-relative path without `.md` (primary key), e.g. `plans/Garden Plan` |
| `path` | vault-relative path with `.md` |
| `title` | frontmatter `title`, else first `# heading`, else filename stem |
| `tags` | comma-joined frontmatter tags (denormalized; canonical set in `tags`) |
| `aliases` | comma-joined frontmatter aliases (canonical set in `aliases`) |
| `content_hash` | sha256 of the raw file text |
| `body` | raw file text (the offset base for section char ranges) |
| `profile` | resolved profile name (see the SKILL's Profiles section) |
| `weight` | ranking multiplier from config, default `1.0` |
| `doc_date` | note-level date from frontmatter, if one was inferred |
| `status` | `hot` |

There is deliberately no `observed_at` here. The graph is defined by the
vault's bytes, not by when they were read: a per-note timestamp would differ
between two builds of unchanged bytes, and the determinism contract allows
exactly one value.

## sections

The retrieval unit. Every note yields at least one section; a profile decides
what one unit is, and every heading beneath a unit is indexed as a child.

| column | meaning |
|---|---|
| `id` | deterministic: `<note id>#<heading path>` plus `~n` only when a path repeats. Never a rowid - citations and mentions must survive a re-ingest |
| `note_id` | `notes.id` |
| `parent_id` | the enclosing unit's section id, or `''` |
| `heading` | the section's own heading text |
| `heading_path` | ` > `-joined ancestor headings, `''` for a note's preamble |
| `level` | heading level, `0` for a preamble |
| `ord` | position within the note |
| `char_start` / `char_end` | offsets into `notes.body`; internal |
| `line_start` / `line_end` | 1-indexed inclusive line range; **the load-bearing contract** - a caller verifies with a line-oriented read |
| `body` | the section's text, including any sections nested inside it |
| `own_body` | `body` minus nested sections; what aggregates count |
| `doc_date` | ISO date for a dated entry, inherited by its children |
| `slot` | `authored`, `quoted`, `generated`, `instrument`, `routine`, `superseded` or `prep` |
| `weight` | recency tier within the note (newest date 1.0, oldest 1/N; `prep` and undated 1.0) times the superseded discount. Written at ingest, read by no query path: `search` recomputes the tier from `doc_date` and applies the discount from `slot` |
| `words` | word count of `body` |
| `is_unit` | 1 for a declared profile unit |
| `oversize` | 1 when the unit exceeds the size ceiling; it is still stored whole |
| `section_hash` | sha256 prefix of `body`; the key extractions hang on |
| `setext` | 1 when the heading was underlined with `===` or `---` rather than written as ATX; `stats` lists these headings as suspect, because a line directly above a `---` divider parses as a setext heading |

## properties

Every frontmatter key/value except `tags` and `aliases` (those get their own
tables). One row per key; list values are stored comma-joined, mappings as
`k=v` pairs. Ingest also writes `kg-date-order` here for any note whose dated
headings were parsed, recording the field order that was inferred.

## tags / aliases

Normalized frontmatter `tags:` and `aliases:`, one row per value. Leading `#`
is stripped from tags; case is preserved as written, and lookups are
case-insensitive.

## edges

One row per distinct link occurrence, extracted fence-aware (fenced code blocks
and inline code never become edges). Primary key `(src, syntax, kind, target)` -
repeat links to the same target from one note collapse to one row.

| column | meaning |
|---|---|
| `src` | source note id |
| `dst` | resolved note id, NULL otherwise |
| `target` | the target as written, minus `#heading` and `\|alias` (md targets URL-decoded) |
| `syntax` | `wiki` (`[[...]]`) or `md` (`[text](target.md)`) |
| `kind` | `link`, or `embed` for `![[...]]` |
| `status` | `resolved`, `unresolved`, `ambiguous`, or `ignored` (the target exists but an ignore rule excluded it) |
| `section_id` | the section the link was written in, which is how `backlinks` answers "in what context" |

Resolution rules (mirror Obsidian):

- wikilinks resolve vault-wide by case-insensitive basename, then by
  frontmatter alias; a path fragment (`[[projects/Note]]`) disambiguates by
  case-insensitive path suffix; a bare name whose basename collides is recorded
  `ambiguous` with `dst` NULL - the engine never guesses.
- markdown links resolve as relative paths from the source file (or vault-root
  paths when leading `/`); only note targets become edges - external URLs and
  asset targets are skipped and counted in the ingest report. A target with no
  extension is a note target when that path names a note. Reference-style
  links (`[text][label]` plus a `[label]: target` definition) become edges
  like inline ones.
- in `obsidian` link mode (an `.obsidian/` folder, or config
  `link_resolution`), a markdown link that misses its relative path and is not
  an explicit `./`, `../` or `/` path resolves like a wikilink: by basename or
  path suffix, `ambiguous` on a collision. In `relative` mode it stays
  `unresolved`.

Graph traversal (`neighbors`, `path`, `related`, `communities`) runs undirected
over `resolved` edges.

## anchors

One row per link that names a heading or a block, in either syntax:
`[[Note#Heading]]`, `[[Note#A#B]]`, `[[Note#^block]]`, `[x](note.md#heading)`,
and same-note links (`[[#Heading]]`, `[x](#heading)`). The note-level link is
still a row in `edges`; this table adds where inside the note it points.
Every ingest wipes and rebuilds it, and `links --anchors` and
`backlinks --anchors` read it.

| column | meaning |
|---|---|
| `src` | source note id |
| `section_id` | the section the link was written in |
| `dst` | resolved note id, NULL when the note did not resolve; the source note for a same-note link |
| `target` | the note target as written, `''` for a same-note link |
| `anchor` | what followed `#`, as written (md anchors URL-decoded) |
| `dst_section` | the smallest indexed section containing the heading or block. A short heading that was rolled up into its parent resolves to the parent |
| `dst_line` | 1-indexed line of the heading or block in the target note; `0` unless resolved |
| `syntax` | `wiki` or `md` |
| `status` | `resolved`; `anchor-missing` when the note exists and the heading or block does not; otherwise the note-level status (`unresolved`, `ambiguous`, `ignored`) |

A heading matches on its exact text (case-insensitive), then on its plain text
with emphasis characters removed, then on the slug a renderer generates for it
(lowercase, punctuation dropped, spaces as hyphens, `-1`, `-2` for a repeated
heading). `A#B` requires `A` among the ancestors of `B`. Where two headings
match, the first in the note wins. A `^id` matches a block identifier at the
end of a line or on a line of its own.

## link_fields

One row per link written under a named field: a frontmatter key or an inline
field (`name:: [[Target]]`). The columns are `(src, field, origin, target,
dst, status, section_id)`; `origin` is `frontmatter` or `inline`, and `field`
is lowercased with spaces as hyphens. Every row here is also a row in
`edges`; this table adds the name. Every ingest wipes and rebuilds it, and
`fields` reads it.

## inline_tags

The `#tags` written in body text, with columns `(note_id, section_id, tag,
count)`. A tag is
letters, digits, `_`, `-` and `/` after a `#` that starts a line or follows
whitespace, with at least one letter. A `#` in code, in a comment or in
frontmatter is never a tag. The `tags` table stays frontmatter-only, and
`tags --inline` reads both. An ingest rewrites the rows of each note that changed.

## file_links

One row per link to a file that is not a note: code, data, a folder, an
embedded image. These links never become rows in `edges`. Every ingest wipes
and rebuilds the table, and `refs` and `code` read it.

| column | meaning |
|---|---|
| `src` | source note id |
| `section_id` | the section the link was written in, found by the line it sits on |
| `target` | the target as written (md targets URL-decoded) |
| `path` | the vault-relative path the target names. A file outside the vault keeps its leading `../` |
| `syntax` | `md` for an inline or reference-style markdown link; `wiki` for a wikilink or embed whose extension is an asset type |

A markdown link is resolved relative to the source file's folder, or to the
vault root when it starts with `/`, and nothing is checked on disk: a link to a
file that is gone still has its row. A wikilink names a file by the end of its
path, as Obsidian resolves it, so its `path` is the target as written, and
`refs` matches it against the end of the requested path. A markdown image (`![alt](file.png)`) is
not a link and has no row.

## code_spans

The inline code spans that are shaped like a path or a name, with columns
`(note_id, section_id, text, line)`: one row per distinct span per section,
and `line` is the span's first use in that section. A span qualifies when it is one token of
letters, digits and `_ . / ~ @ : # -` with a letter in it, 2 to 200 characters,
optionally ending in `()`, and not starting with `-`. Spans in frontmatter,
fenced code and comments are not read. Nothing is resolved at ingest: the
table holds what the note says, and `code --mentions` asks the `code-kg` skill
what each span refers to at read time, so a change in the code never makes
this table stale. Every ingest wipes and rebuilds it, and `spans` reads it.

## members

List members of a `dimension`-profile note: `(section_id, note_id, group_name,
name, ord)`. The group heading names the group; each list item under it is one
member.

## entities / entity_aliases / mentions

The registry, derived from the config file's `entities` array and therefore
rebuilt every ingest.

- `entities(canonical, type, time, note, t_start, t_end, origin)` - `type` is
  free text and nothing branches on it. `time` is `static`, `evolving`, or
  `bounded` with `t_start`/`t_end` filled from a `<start>..<end>` config value.
  `origin` is `config` for a hand-written row and `note` for one an
  `entity_sources` row derived.
- `entity_skips(note_id, name, reason)` - derived names an ingest left out: a
  note a hand-written row already names, a name another entity already claims,
  or a name shorter than three characters. `config` reports them.
- `entity_aliases(canonical, alias)` - the canonical name plus every declared
  alias. An alias claimed by two canonicals fails the ingest loudly.
- `mentions(canonical, section_id, note_id, doc_date, count)` - gazetteer hits
  in `own_body`, case-insensitive on word boundaries, longest alias winning,
  possessives and plurals folded in. Matches inside code fences do not count.

## ignored

`(path, rule)` for every file an ignore rule excluded, so `stats` can report
what was left out and which rule matched.

## other_files

`(path, ext, size, reason)` for every file in the vault that is not a note:
attachments, data and anything else the walk sees, listed by `tree` and
never opened. `reason` is `no-parser`. Rebuilt by every ingest; a change to
any of these files is drift, so `tree` stays current.

## annotations / annotation_candidates

One `annotations` row per registered `**MARKER**:` line: `(note_id,
section_id, line, marker, payload, target, date)`. `section_id` is the
smallest section containing the line ('' when nothing does), `target` the
first wikilink target in the payload, `date` a leading `YYYY-MM-DD` when one
parses. Wiped and rebuilt every ingest. `ANCHOR` rows are read by `search` at
query time; `SUPERSEDED` never needs reading at query time because ingest
already set the section's slot.

`annotation_candidates` aggregates the near-misses per `(token, kind)`:
`unregistered` for a grammar match with an unknown token, `placement` for a
marker written indented, bulleted, blockquoted or in a table cell. Counts
only, never line text - it feeds the capped `stats` report.

## extractions / conflicts

The judgment tables; an ingest never wipes them. `extractions`
keys on `section_hash`, so a re-ingest keeps prior work and only re-extracts
what changed; an extraction whose section is gone flips to `status='cold'` with
its quote and provenance intact, and flips back to `hot` if the section
returns. `conflicts` carries a `resolution` that stays empty until someone
rules. Nothing is silently reconciled and nothing is deleted.

`relate` writes `extractions` rows of `kind='relation'` - the INFERRED lane of
edge provenance. `subject` is the anchoring section's note, `object` a
resolved note id, `predicate` free text, and the `quote` is verified to occur
in the anchoring section at write time (`q_start`/`q_end` are absolute file
offsets). Everything in `edges` is EXTRACTED provenance (explicit link syntax
in the corpus); ingest never writes an inferred relation. Traversal commands
join hot inferred relations only behind `--include-inferred`; cold rows never
traverse, because their evidence moved. `relate` also writes a `conflicts` row
(`kind='relation'`) when the same subject and predicate already point at a
different object; `relations --conflicts` is the worklist,
`relations --resolve <seq> "<ruling>"` records the ruling and closes it, and
`relations --retire <id>` is the exit for a wrong relation: status flips to
`retired` - sticky, never resurrected by reconcile, out of traversal, the
default listing, and the dup/conflict checks, with the row and its evidence
kept per the never-delete rule. Contradiction detection over entities remains
phase 2.

## session_reads

The coverage ledger, appended by `--session <id>` on `query`, `search`, `read`
and `sections`, read by `coverage`. One row per (session, section); first touch
wins, keeping the command that surfaced it and a UTC timestamp. Never wiped by
ingest; rows whose section is gone count as `stale` in `coverage` output.
`coverage --forget <id>` deletes a session.

## meta

`ingested_at` (UTC ISO-8601) - the only non-deterministic content in the file -
and `manifest`, a fingerprint of the vault's file set plus the engine's
`INDEX_REV`, which every read command compares before answering, re-ingesting on
drift or after a parser or schema change.

## Full-text index

`sections_fts` - FTS5 external-content table over `(heading_path, body)`,
rebuilt wholesale at the end of each ingest. Indexing is **section-level only**:
whole-file matching is the failure this schema exists to fix, so there is no
`notes_fts`. Title and filename matching happens against `notes` directly.

## Conventions

- `ingest` is an idempotent **full rebuild**: every derived table is wiped and
  re-populated in sorted file order, so the same vault bytes always produce the
  same rows. `extractions`, `conflicts` and `session_reads` are the
  exceptions.
- The DB is disposable: delete it and re-run `ingest`. The config file is not -
  it is the curation, which is exactly why it lives outside the database.
- Read commands re-ingest on their own when the vault has drifted, and exit
  nonzero with a "run `ingest`" message when there is no DB at all.

# markdown-kg.db schema reference

`markdown_kg.py` creates the SQLite database at `<vault>/markdown-kg/markdown-kg.db`, beside `markdown-kg-config.md`.
A vault built before the folder was renamed has the database at the legacy `vault-kg/vault-kg.db`, and the engine keeps using that file in place.
Read this before writing raw SQL against the DB; prefer the CLI subcommands otherwise.

## Contents

- [notes](#notes)
- [sections](#sections)
- [properties](#properties)
- [tags / aliases](#tags--aliases)
- [edges](#edges)
- [anchors](#anchors)
- [link_fields](#link_fields)
- [inline_tags](#inline_tags)
- [members](#members)
- [entities / entity_aliases / mentions](#entities--entity_aliases--mentions)
- [ignored](#ignored)
- [annotations / annotation_candidates](#annotations--annotation_candidates)
- [extractions / conflicts](#extractions--conflicts)
- [session_reads](#session_reads)
- [meta](#meta)
- [Full-text index](#full-text-index)
- [Conventions](#conventions)

## notes

One row per ingested markdown file.
Dot folders such as `.obsidian`, `.git` and `.trash`, the folders in `SKIP_FOLDERS` and the engine's own folder under either name (`markdown-kg/` or the legacy `vault-kg/`) are never ingested.
Enumeration is a filesystem walk, so gitignored notes and notes
inside a nested git repo are ingested like any other; exclusion belongs to
the engine's own ignore rules. Files excluded by an ignore rule are not here
at all; see [ignored](#ignored).

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

There is deliberately no `observed_at` here. The table is wiped and rebuilt
every ingest, so a per-note timestamp would only restate `meta.ingested_at`
while introducing a second value that differs between two ingests of unchanged
bytes - and the determinism contract allows exactly one.

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
`tags --inline` reads both. Every ingest wipes and rebuilds this table.

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

# code-kg database schema

SQLite + FTS5 at `<repo>/.code-kg/code-kg.db`. Every ingest rebuilds the db
whole except for two groups of tables. `coverage`, `runs` and the
`observed_*` tables survive so execution evidence outlives a re-parse, and
`session_reads`, `extractions` and `conflicts` survive because they hold
what sessions read and judged. `ingest --keep-previous` first copies the db
to `code-kg-prev.db`, the checkpoint `diff` compares against. All paths are
repo-relative posix.

## Tables

### files
| column | meaning |
|---|---|
| `id` | repo-relative path (the primary key everything joins on) |
| `language` | python, javascript, typescript, bash, dockerfile, yaml, terraform, sql, markdown, json, toml, make, html, css, go, rust, c, java, csharp, msbuild, powershell; `fish`, `csh` and `batch` are indexed for search but not parsed. A file with no extension takes the language its `#!` line names |
| `role` | `source`, `test`, `config`, `docs`, `ci` |
| `size`, `lines` | bytes, line count |
| `content_hash` | sha256 of the text |
| `body` | full file text (line-range reads slice this) |
| `parse_error` | non-empty when a parser failed; the file is still indexed for search |
| `origin` | `project` or `dep`. Dependency files (opt-in via config `deps`) are searchable only with `--deps`, carry symbols but no edges of their own, and never join liveness |

### symbols
| column | meaning |
|---|---|
| `id` | `<file>::<qualname>` (duplicates disambiguated `~2`, `~3`...) |
| `kind` | function, class, method, interface, type, enum, target, table, view, resource, module...; `stage` (a Dockerfile `FROM`, qualname `stage.<alias>` or `stage.<index>`), `service` (compose, `services.<name>`), `job` (GitHub workflow, `jobs.<name>`), `script` (package.json, `scripts.<name>`) |
| `line_start`, `line_end` | 1-indexed inclusive. Exact for python (AST), Dockerfile stages, compose services, workflow jobs and package.json scripts; for regex-scanned languages the end is approximate: the line before the next symbol, or the return to the symbol's own indentation if that comes first |
| `exported` | 1 unless underscore-private (python) or unexported (js) |

### edges
| column | meaning |
|---|---|
| `src`, `dst` | file ids; `dst` NULL unless status is `resolved` |
| `target` | the reference as written in the source |
| `kind` | see below |
| `status` | `resolved`, `external`, `dep`, `unresolved`, `excluded`, `ambiguous` |

Edge kinds, strongest first:

- **Executable** (`import`, `from-import`, `from-import-sub`, `pkg-init`,
  `require`, `dynamic-import`, `reexport`, `source`, `exec`, `module`,
  `uses`, `script`, `include`) - the reference implies the target loads or
  runs. These drive liveness. `from-import-sub` is a `from pkg import
  submodule` resolved to the submodule file; `pkg-init` records that
  importing `pkg.mod` executes every ancestor `__init__.py`.
- **Weak** (`path-ref`, `link`, `copy`) - a string literal naming a repo
  path, a markdown/html link, or a Docker COPY / compose mount. Evidence of
  presence or reference, not of execution - dead code ships in images all
  the time. Directory COPYs/mounts are expanded to the files under them
  (capped at 200), each edge carrying the expanded path as its target.
- `include-sys` (`#include <...>`) is recorded external and never joins
  liveness.
- **Declared** (`declared`, `declared-live`) - written by a config `links`
  row, line `0`, target equal to the destination path. `declared` is weak;
  `declared-live` is executable and drives liveness like an import.

Statuses: `resolved` means the target exists in this repo; `external` means
a package, stdlib module, base image or marketplace action outside the repo;
`dep` means an external import whose package code is indexed (dst is the
package's entry file, but the edge never joins liveness); `unresolved`
means it looks local and does not exist (a worklist item); `ambiguous`
means two candidates matched and none was chosen.

### symbol_edges
Rebuilt by every ingest. Python is read with `ast`; JS/TS, bash, SQL,
HTML, Dockerfiles, YAML, package.json, Makefiles and Terraform are read
with stdlib scanners that blank comments and strings first. SKILL.md, under
Interpreting output, lists what each language records.

| column | meaning |
|---|---|
| `src_file` | the file the row was read from |
| `src` | symbol id, or `<file>::<module>` for a file's top-level code |
| `dst` | symbol id, or `<file>::<module>` for a script a command runs; NULL unless status is `resolved` |
| `target` | the callee or name as written, capped at 120 characters |
| `kind` | `call`, `ref` (a function or class used as a value; a Terraform reference; a COPY `--from` or a compose `build`), `import`, `decorated-by`, `extends` (also a Dockerfile `FROM`), `depends-on` (compose `depends_on`, workflow `needs`, Terraform `depends_on`). With `--include-inferred`, `callers` and `callees` add `inferred/<predicate>` rows from `relate` at query time |
| `status` | `resolved`, `weak`, `ambiguous`, `external`, `unresolved` |
| `provenance` | `extracted` |
| `candidates` | for `weak` and `ambiguous`, the method ids of that name, newline-joined, at most 20 |

A def nested inside a function is not a symbol: its calls are filed under
the enclosing symbol.

### data_edges
Rebuilt by every ingest from Python, SQL (`table`), HTML, CSS and JSX
`className` (`css-*`). `env` rows come from every place a setting is
defined or read: Python, shell text (bash files, Dockerfile `RUN`, workflow
`run`, package.json scripts), Dockerfile `ENV`/`ARG`, compose `environment`
and `${NAME}` interpolation, workflow `env:` and `${{ env.NAME }}`, and
Kubernetes `env` lists. Only literal names are recorded; a table, file or
variable name built at run time is not guessed.

| column | meaning |
|---|---|
| `src` | symbol id, or `<file>::<module>` |
| `kind` | `read`, `write`, `open` (a database file), `define` and `use` (CSS names), `passes` (an argument of a resolved call), `param` (one row per parameter, numbered as callers pass them) |
| `node_kind` | `global`, `table`, `file`, `env`, `config`, `css-class`, `css-id`, `css-var`, `literal`, `param` |
| `node` | the name; `param:<name>` when the caller's parameter names it; a global is `file::NAME` |
| `status` | `resolved` (named in the source), `param` (named by a parameter), `weak` (a config key found by receiver name, or a shell `$NAME` read of a name the file does not define as environment, which may be a shell variable) |
| `provenance` | `extracted`; `flow` reports a row it reached through a call as `inferred`, at query time |
| `via` | the call that touches the node, or `callee#arg` for `passes` |

Tables come from SQL string literals passed to `execute`, `executemany`
and `executescript`: INSERT, UPDATE, DELETE, CREATE, DROP and ALTER write;
FROM and JOIN read.

### observed_calls / observed_entries / observed_lines
Written by `coverage run --yes --calls`, keyed by `run_id` (a `runs` row of
kind `trace-run` whose `detail` holds the command, exit code, process count
and the tree manifest at run time). Like `coverage`, these tables survive
ingest; `observed_lines` is pruned to files still indexed.

| table | columns |
|---|---|
| `observed_calls` | `run_id`, `src` (caller symbol or `<file>::<module>`), `dst` (callee symbol), `line` (the caller's line), `count` |
| `observed_entries` | `run_id`, `symbol`, `count` |
| `observed_lines` | `run_id`, `file_id`, `line` |

### entry_points
Detected roots for reachability: `main-guard` (python/go/rust/c/java/c#),
`shebang`, `script` (pyproject console script, msbuild Exe), `bin`
(package.json), `dockerfile`, `compose`, `workflow`, `make`, `page`
(index.html), `config` (declared in config.json). A test file's own entry
points never seed the live tier - that is what keeps `test-only` meaningful.

### coverage / runs
`coverage(file_id, line, hits)` holds max hits per line across every
ingested artifact or consented run; `runs` is the append-only event log.
Both survive re-ingest; coverage rows for deleted files are pruned.

### ignored
What an ingest excluded and why: `config:<glob>`, `oversize`,
`symlink-or-escape`.

### other_files
`(path, ext, size, reason)`: one row per file the walk saw that no parser
reads, listed by `tree` and never opened. `reason` is `no-parser`, `policy`
(lockfiles) or `secret-name` (`.env*`, `secrets.*`, `*.tfvars`). Rebuilt by
every ingest.

### session_reads
`(session_id, unit_id, file_id, cmd, at)`: what `search`, `query` and
`read` returned under `--session`, with only the first touch kept.
`unit_id` is a symbol id, or a file id when the whole file was returned.
`reads` reports this table.

### extractions / conflicts
These tables hold the judgments `relate` records. In `extractions(id,
unit_id, unit_hash, kind, subject, predicate, object, quote, line,
observed_at, status)`, `unit_id` anchors the quote and `status` is `hot`,
`cold` (the anchor changed or is gone) or `retired` (sticky).
`conflicts(seq, detected_at, key, kind, a_extraction, b_extraction,
resolution, state)` records two hot relations with one subject and
predicate and different objects. Every ingest re-checks each anchor's hash.

### components
`(name, file_id)`: one row per file a config `components` row matched. A file
in two components has two rows. Names, aliases and descriptions stay in the
config; `components` reads both.

### annotations
`(file_id, line, marker, owner, payload, symbol_id)`: one row per comment
marker in a project file. `owner` is the name in `TODO(name):`, `symbol_id` the
innermost symbol containing the line or `''`. Capped at 20000 rows per ingest;
`meta.annotations_seen` holds the uncapped count.

### meta
`manifest` is the fingerprint read commands compare before answering: every
file the walk sees, the config, lockfiles and the engine's `INDEX_REV`, so a
parser or schema change re-ingests an unchanged repo once.

### FTS
`symbols_fts(id, qualname, body)` indexes each symbol's text slice;
`files_fts(id, path, body)` indexes whole files. `search` tries symbols
first, then files, on a rung ladder (phrase, all-terms, any-term).

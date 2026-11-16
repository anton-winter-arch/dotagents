# code-kg database schema

SQLite + FTS5 at `<repo>/.code-kg/code-kg.db`. Rebuilt whole by every ingest
except `coverage` and `runs`, which survive so execution evidence outlives a
re-parse. All paths are repo-relative posix.

## Tables

### files
| column | meaning |
|---|---|
| `id` | repo-relative path (the primary key everything joins on) |
| `language` | python, javascript, typescript, bash, dockerfile, yaml, terraform, sql, markdown, json, toml, make |
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
| `kind` | function, class, method, interface, type, enum, target, table, view, resource, module... |
| `line_start`, `line_end` | 1-indexed inclusive. Exact for python (AST); for regex-scanned languages the end is the line before the next symbol, which is approximate |
| `exported` | 1 unless underscore-private (python) or unexported (js) |

### edges
| column | meaning |
|---|---|
| `src`, `dst` | file ids; `dst` NULL unless status is `resolved` |
| `target` | the reference as written in the source |
| `kind` | see below |
| `status` | `resolved`, `external`, `unresolved`, `ambiguous` |

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
Rebuilt by every ingest. Python is read with `ast`; JS/TS, bash, SQL and
HTML with stdlib scanners that blank comments and strings first (see
SKILL.md for what each language records).

| column | meaning |
|---|---|
| `src_file` | the file the row was read from |
| `src` | symbol id, or `<file>::<module>` for a file's top-level code |
| `dst` | symbol id; NULL unless status is `resolved` |
| `target` | the callee or name as written, capped at 120 characters |
| `kind` | `call`, `ref` (a function or class used as a value), `import`, `decorated-by`, `extends` |
| `status` | `resolved`, `weak`, `ambiguous`, `external`, `unresolved` |
| `provenance` | `extracted` |
| `candidates` | for `weak` and `ambiguous`, the method ids of that name, newline-joined, at most 20 |

A def nested inside a function is not a symbol: its calls are filed under
the enclosing symbol.

### data_edges
Rebuilt by every ingest: Python, bash (`env`), SQL (`table`), HTML and CSS
(`css-*`). Literal names only: a table, file or variable name built at run
time is not guessed.

| column | meaning |
|---|---|
| `src` | symbol id, or `<file>::<module>` |
| `kind` | `read`, `write`, `open` (a database file), `define` and `use` (CSS names), `passes` (an argument of a resolved call), `param` (one row per parameter, numbered as callers pass them) |
| `node_kind` | `global`, `table`, `file`, `env`, `config`, `css-class`, `css-id`, `css-var`, `literal`, `param` |
| `node` | the name; `param:<name>` when the caller's parameter names it; a global is `file::NAME` |
| `status` | `resolved` (named in the source), `param` (named by a parameter), `weak` (config keys, found by receiver name) |
| `via` | the call that touches the node, or `callee#arg` for `passes` |

Tables come from SQL string literals passed to `execute`, `executemany`
and `executescript`: INSERT, UPDATE, DELETE, CREATE, DROP and ALTER write;
FROM and JOIN read.

### observed_calls / observed_entries / observed_lines
Written by `coverage run --yes --calls`, keyed by `run_id` (a `runs` row of
kind `trace-run` whose `detail` holds the command, exit code, process count
and the tree manifest at run time). They survive ingest like `coverage`;
`observed_lines` is pruned to live files.

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
`manifest` is the fingerprint read commands compare before answering: the
indexable file set, the config, lockfiles and the engine's `INDEX_REV`, so a
parser or schema change re-ingests an unchanged repo once.

### FTS
`symbols_fts(id, qualname, body)` indexes each symbol's text slice;
`files_fts(id, path, body)` indexes whole files. `search` tries symbols
first, then files, on a rung ladder (phrase, all-terms, any-term).

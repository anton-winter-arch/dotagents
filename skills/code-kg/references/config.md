# code-kg config reference

`<repo>/.code-kg/config.json`, one JSON object. A missing config is valid:
every field defaults to empty. Edit the file directly.

```json
{
  "ignore": ["generated/**", "*.pb.py"],
  "roots": ["backend/src"],
  "entry_points": ["tools/nightly_job.py", "jobs/**/handler.py"],
  "aliases": {"@/*": "src/*"},
  "profile": "",
  "test_command": "python3 -m coverage run -m pytest -q"
}
```

## Fields

- **ignore** - glob patterns (same dialect as .gitignore's common core: `*`
  within a segment, `**` across segments, bare names match any path part).
  Matched files are recorded in the `ignored` table with the rule that
  excluded them, so an ignore is always auditable. Use for generated code,
  third-party trees, and fixtures that would pollute liveness.
- **roots** - extra Python import roots besides the repo root. `src/` is
  auto-detected; add others (`backend/`, `services/api/`) when absolute
  imports resolve from somewhere deeper. A wrong root shows up as a burst of
  `unresolved` python edges - run `unresolved` to check.
- **entry_points** - repo-relative paths or globs to treat as reachability
  roots on top of the detected ones (main guards, shebangs, packaging
  scripts/bins, Dockerfiles, compose files, workflows, Makefiles, framework
  convention files). Use for jobs invoked by external schedulers the repo
  cannot see - cron entries, serverless handlers, plugin hooks. An entry
  that matches nothing is warned about at ingest, never silently ignored.
- **aliases** - import-alias map merged after autodetection (tsconfig
  `paths`, package.json `imports`); config wins on pattern collision.
  Single-star patterns only. The escape hatch for Vite/webpack/Deno-import-
  map conventions the engine deliberately does not parse.
- **profile** - framework profile override: `"django"`, `"nextjs"`, or
  `"generic"` to disable convention rules. Empty (default) auto-detects and
  prints the result at init/ingest.
- **deps** - `"none"` (default) or `"referenced"`. Referenced mode indexes
  the code of dependencies the project imports, from repo-local installs
  only (`.venv`, `venv`, `node_modules`), tagged `origin='dep'`: searchable
  with `--deps`, readable by path or symbol id, excluded from liveness and
  default search. Caps: 400 files per package, 4000 total (overflow lands
  in `ignored` as `dep-cap`). Drift detection watches lockfiles rather than
  the dependency tree, so run `ingest` after installing packages.
- **test_command** - what `coverage run --yes` executes, split with shlex,
  cwd at the repo root - this is also the override for repos whose runner
  needs flags (e.g. `python3 -m coverage run manage.py test core
  --settings=config.settings_test`). When empty, detection prefers the
  Django runner (`manage.py test`) on Django repos without pytest config,
  else pytest under coverage.py. JS test scripts are never auto-run (their
  coverage flags are repo-specific); the refusal names the script it saw.
  A custom command is expected to leave a standard artifact
  (`coverage.json`, `lcov.info`, `coverage/coverage-final.json`) for
  auto-ingest. The value must be one line of printable text: a control or
  invisible character is refused, because `coverage run` shows this command
  for consent before it runs.

## Extension keys

All three are optional, and an absent key is empty, so a config written before they existed loads exactly as it did.
`init` does not scaffold them.
Paths are globs in the same dialect as `ignore`; nothing in the config is ever compiled as a regular expression or executed, and names must be one line of printable text.
Each key takes at most 200 rows, and a component at most 50 paths and 50 aliases, because every row is a pass over the file list at ingest.

```json
{
  "components": [
    {"name": "billing", "aliases": ["invoicing"],
     "description": "invoices and payments",
     "paths": ["core/services/billing.py", "core/api/**"]}
  ],
  "links": [
    {"from": "app/registry.py", "to": "app/plugins/*.py", "live": true,
     "reason": "plugins are imported by name at run time"}
  ],
  "markers": ["SAFETY"]
}
```

- **components** - each row names a group of files, the code analog of a registered entity.
  `name` and `paths` are required; `aliases` and `description` are optional, and a name or alias may belong to one component only.
  `components <repo>` lists each group with its file and line counts, what it depends on and what uses it, counted as resolved executable edges that cross from one component into another.
  `components <repo> NAME` lists the members and every crossing edge.
  A file matched by two components counts in both and is listed under overlaps; source files in no component are listed as unassigned.
- **links** - declared edges, for wiring the repo knows about and no parser can see.
  Each row expands to an edge from every file matching `from` to every file matching `to`, capped at 2000 edges per row.
  The edge kind is `declared`, a weak reference that shows in `importers`, `neighbors` and `path` and never changes liveness.
  With `"live": true` the kind is `declared-live`, which counts as an executable edge: use it when the target really runs, such as a plugin a registry imports by name.
  `reason` is free text for the next reader.
  A row with an empty side is warned about at ingest and by `config`, never silently ignored.
- **markers** - extra comment markers for `annotations`, each 2 to 32 characters of `A-Z`, `0-9` and hyphen.
  The core set (`TODO`, `FIXME`, `HACK`, `XXX`, `NOTE`, `BUG`) is always on and cannot be re-registered.
  A marker counts when it follows a comment leader for the file's language, so the word alone in code or prose is not one.
  The scan is line-based and does not parse strings, which makes its output a worklist to read.

`config <repo>` reports what every row in the file matched and writes nothing.
A row that matches nothing is a warning; only a malformed file is an error.

## Built-in exclusions (not configurable)

Dot folders (except `.github` and the agent-tooling layer: `.claude`,
`.agents`, `.cursor`), `node_modules`, virtualenvs, build output,
caches, lockfiles, minified bundles, files over 2 MB, and symlinks -
symlinked "source" pointing outside the repo is refused and recorded, never
followed.

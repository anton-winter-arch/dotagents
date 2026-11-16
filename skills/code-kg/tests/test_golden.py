#!/usr/bin/env python3
"""Golden-output guard for code_kg.py.

Every command that existed before the extension keys is run over the
committed fixture repos, and its output is compared with a stored capture in
`golden/`. An engine change that alters what an existing command prints, or
what an existing table holds, fails here before it reaches a real repo. New
commands, flags and tables are covered by their own tests, never by this file.

Regenerate deliberately, after reading the diff:
`python3 skills/code-kg/tests/test_golden.py --update`."""
import contextlib
import difflib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import code_kg  # noqa: E402
from fixture_copy import copy_fixture  # noqa: E402

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
FIXTURES = ("fixture-repo", "fixture-relay", "fixture-django",
            "fixture-nextapp", "fixture-deps", "lang-samples")
TERMS = ("invoice", "load config", "main", "render", "token")
SAMPLE = 10
STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# Explicit column lists: a column added to one of these tables later must not
# read as a change to what the table held before.
DUMPS = {
    "files": "SELECT id, language, role, size, lines, content_hash,"
             " parse_error, origin FROM files ORDER BY id",
    "symbols": "SELECT id, file_id, kind, name, qualname, line_start,"
               " line_end, exported FROM symbols ORDER BY id",
    "edges": "SELECT src, dst, target, kind, line, status FROM edges"
             " ORDER BY src, kind, target, line",
    "entry_points": "SELECT file_id, kind, detail FROM entry_points"
                    " ORDER BY 1, 2, 3",
    "ignored": "SELECT path, rule FROM ignored ORDER BY 1",
}


def run(repo: Path, *argv: str) -> dict:
    """One engine call in-process: exit code plus normalized stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = code_kg.main(list(argv))
        except SystemExit as e:
            if isinstance(e.code, int) or e.code is None:
                rc = e.code or 0
            else:
                rc = 1
                err.write(str(e.code))
    return {"rc": rc, "out": _norm(out.getvalue(), repo),
            "err": _norm(err.getvalue(), repo)}


def _norm(text: str, repo: Path) -> str:
    for p in sorted({str(repo), str(repo.resolve())}, key=len, reverse=True):
        text = text.replace(p, "<REPO>")
    return STAMP_RE.sub("<UTC>", text)


def capture(fixture: str) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="codekg-golden-"))
    try:
        repo = tmp / "repo"
        copy_fixture(HERE / fixture, repo)
        r = str(repo)
        got: dict = {}

        def call(*argv: str) -> None:
            key = " ".join(a if a != r else "<REPO>" for a in argv)
            got[key] = run(repo, *argv)

        call("init", r)
        call("ingest", r, "--json")
        con = sqlite3.connect(code_kg.db_path(repo))
        got["tables"] = {name: [list(row) for row in con.execute(sql)]
                         for name, sql in DUMPS.items()}
        files = [row[0] for row in con.execute(
            "SELECT id FROM files WHERE origin='project' ORDER BY id")]
        con.close()

        for cmd in (("stats",), ("entrypoints",), ("dead",), ("god-nodes",),
                    ("communities",), ("unresolved",), ("externals",),
                    ("data",), ("coverage", "report")):
            call(cmd[0], r, *cmd[1:])
            call(cmd[0], r, *cmd[1:], "--json")
        # The table dump above covers every file; the per-file commands guard
        # rendering, and an even sample keeps the capture small and fast.
        for fid in files[::max(1, len(files) // SAMPLE)][:SAMPLE]:
            for cmd in ("file", "symbols", "imports", "importers"):
                call(cmd, r, fid, "--json")
            call("neighbors", r, fid, "--depth", "2", "--json")
        if len(files) > 1:
            call("path", r, files[0], files[-1], "--json")
            call("read", r, files[0])
        for term in TERMS:
            call("search", r, term, "--json")
            call("search", r, term)
            call("query", r, term, "--json")
        call("index", r)
        return got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def golden_path(fixture: str) -> Path:
    return GOLDEN / f"{fixture}.json"


def _show(value) -> list[str]:
    return json.dumps(value, indent=2, sort_keys=True,
                      ensure_ascii=False).splitlines()


class GoldenTests(unittest.TestCase):
    maxDiff = None

    def check(self, fixture: str) -> None:
        want = json.loads(golden_path(fixture).read_text(encoding="utf-8"))
        got = json.loads(json.dumps(capture(fixture)))
        self.assertEqual(sorted(want), sorted(got),
                         "the set of captured commands changed")
        for key in sorted(want):
            if want[key] != got[key]:
                diff = "\n".join(list(difflib.unified_diff(
                    _show(want[key]), _show(got[key]), "golden", "now",
                    lineterm=""))[:80])
                self.fail(f"{fixture}: output changed for `{key}`\n{diff}")

    def test_fixture_repo(self):
        self.check("fixture-repo")

    def test_fixture_relay(self):
        self.check("fixture-relay")

    def test_fixture_django(self):
        self.check("fixture-django")

    def test_fixture_nextapp(self):
        self.check("fixture-nextapp")

    def test_fixture_deps(self):
        self.check("fixture-deps")

    def test_lang_samples(self):
        self.check("lang-samples")

    def test_output_does_not_depend_on_the_hash_seed(self):
        """Set iteration order changes with PYTHONHASHSEED, so any output
        ordered by a set differs between two runs of the same command. The
        three small fixtures cover every command; the large ones add time."""
        for fixture in ("fixture-repo", "fixture-deps", "lang-samples"):
            dumps = []
            for seed in ("1", "2"):
                r = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--dump",
                     fixture], capture_output=True, text=True,
                    env={**os.environ, "PYTHONHASHSEED": seed})
                self.assertEqual(r.returncode, 0, r.stderr[-400:])
                dumps.append(json.loads(r.stdout))
            for other in dumps[1:]:
                for key in sorted(dumps[0]):
                    self.assertEqual(dumps[0][key], other[key],
                                     f"{fixture}: `{key}` varies by hash seed")


if __name__ == "__main__":
    if "--dump" in sys.argv:
        print(json.dumps(capture(sys.argv[sys.argv.index("--dump") + 1]),
                         sort_keys=True))
        sys.exit(0)
    if "--update" in sys.argv:
        GOLDEN.mkdir(exist_ok=True)
        for name in FIXTURES:
            golden_path(name).write_text(
                json.dumps(capture(name), indent=1, sort_keys=True,
                           ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {golden_path(name)}")
        sys.exit(0)
    unittest.main()

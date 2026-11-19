"""An ingest that reuses the parse cache and rewrites only changed files
must leave the graph a cold build leaves, after every kind of change:
an unchanged tree, a body edit, an edit in one file that changes how
another resolves, a file added and removed, and a tampered cache.

Run: python3 -m unittest discover -s tests
"""
import contextlib
import io
import os
import sqlite3
import subprocess
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import code_kg  # noqa: E402
from fixture_copy import copy_fixture  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture-repo"
STORE = ("class Store:\n    def save(self):\n        return 1\n\n\n"
         "class Other:\n    def keep(self):\n        return 2\n\n\n"
         "HOME = Store()\n")
USE = ("from app.store import HOME\n\n\n"
       "def go():\n    return HOME.save()\n")


class IncrementalIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-inc-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(self.tmp / "state")
        code_kg.ParseCache._source = None
        self.addCleanup(lambda: os.environ.pop("XDG_STATE_HOME", None)
                        if old is None
                        else os.environ.__setitem__("XDG_STATE_HOME", old))
        self.addCleanup(setattr, code_kg.ParseCache, "_source", None)
        self.repo = copy_fixture(FIXTURE, self.tmp / "repo")
        (self.repo / "app" / "store.py").write_text(STORE, encoding="utf-8")
        (self.repo / "app" / "use.py").write_text(USE, encoding="utf-8")

    def ingest(self) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            code_kg.ingest(self.repo)
        return self.graph()

    def cold(self) -> dict:
        code_kg.db_path(self.repo).unlink()
        return self.ingest()

    def graph(self) -> dict:
        """Every table but meta and the cache as sorted rows; the text
        indexes by their content, since an update and a rebuild lay out
        their internal tables differently."""
        con = sqlite3.connect(code_kg.db_path(self.repo))
        out = {}
        for (table,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'"):
            if table in ("meta", "parse_cache") or "_fts_" in table:
                continue
            out[table] = sorted(map(repr, con.execute(
                f'SELECT * FROM "{table}"')))
        con.close()
        return out

    def edge(self, src: str) -> list:
        con = sqlite3.connect(code_kg.db_path(self.repo))
        rows = con.execute("SELECT dst, status FROM symbol_edges"
                           " WHERE src = ?", (src,)).fetchall()
        con.close()
        return rows

    def test_an_unchanged_tree_equals_a_cold_build(self):
        self.ingest()
        self.assertEqual(self.ingest(), self.cold())

    def test_a_body_edit_elsewhere_reaches_the_file_that_reads_it(self):
        self.ingest()
        self.assertIn(("app/store.py::Store.save", "resolved"),
                      self.edge("app/use.py::go"))
        store = self.repo / "app" / "store.py"
        # No symbol is added or renamed: only the file use.py resolves
        # through changes, so its cached rows must not be reused.
        store.write_text(STORE.replace("HOME = Store()", "HOME = Other()"),
                         encoding="utf-8")
        warm = self.ingest()
        self.assertNotIn(("app/store.py::Store.save", "resolved"),
                         self.edge("app/use.py::go"))
        self.assertEqual(warm, self.cold())

    def test_edits_in_other_languages_equal_a_cold_build(self):
        self.ingest()
        common = self.repo / "scripts" / "common.sh"
        common.write_text("# moved down a line\n" + common.read_text(),
                          encoding="utf-8")
        api = self.repo / "web" / "lib" / "api.ts"
        api.write_text(api.read_text() + "\nexport const extra = 1;\n",
                       encoding="utf-8")
        self.assertEqual(self.ingest(), self.cold())

    def test_a_compose_file_follows_its_dockerfile(self):
        (self.repo / "docker-compose.yml").write_text(
            "services:\n  api:\n    build:\n      context: .\n"
            "      dockerfile: Dockerfile\n"
            "    command: python3 /srv/app/main.py\n",
            encoding="utf-8")
        self.ingest()
        before = self.rows("docker-compose.yml")
        docker = self.repo / "Dockerfile"
        # The stage keeps its id; only the folder the command runs in moves,
        # so the absolute script path no longer maps back into the repo.
        docker.write_text(docker.read_text().replace(
            "WORKDIR /srv", "WORKDIR /opt"), encoding="utf-8")
        warm = self.ingest()
        self.assertNotEqual(before, self.rows("docker-compose.yml"))
        self.assertEqual(warm, self.cold())

    def test_a_database_from_another_machine_is_rewritten(self):
        self.ingest()
        con = sqlite3.connect(code_kg.db_path(self.repo))
        con.execute("UPDATE symbols SET name = 'planted'"
                    " WHERE file_id = 'app/util.py'")
        con.commit()
        con.close()
        os.environ["XDG_STATE_HOME"] = str(self.tmp / "other-station")
        code_kg.ParseCache._source = None
        self.assertEqual(self.ingest(), self.cold())

    def test_reads_at_once_after_an_edit_all_answer(self):
        # Each read finds the drift; one rebuilds, the rest wait and reuse
        # it, and none fails on a locked database.
        self.ingest()
        util = self.repo / "app" / "util.py"
        util.write_text(util.read_text() + "\n\ndef added():\n    return 1\n",
                        encoding="utf-8")
        env = {**os.environ, "XDG_STATE_HOME": str(self.tmp / "state")}
        procs = [subprocess.Popen(
            [sys.executable, str(code_kg.Path(code_kg.__file__)), "search",
             str(self.repo), "added"], env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True) for _ in range(4)]
        try:
            for p in procs:
                out, err = p.communicate(timeout=120)
                self.assertEqual(p.returncode, 0, err)
                self.assertIn("app/util.py", out)
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.wait()

    def rows(self, src_file: str) -> list:
        con = sqlite3.connect(code_kg.db_path(self.repo))
        out = [sorted(map(repr, con.execute(
            f"SELECT * FROM {table} WHERE src_file = ?", (src_file,))))
            for table in ("symbol_edges", "data_edges")]
        con.close()
        return out

    def test_files_added_and_removed_equal_a_cold_build(self):
        self.ingest()
        (self.repo / "app" / "orphan.py").unlink()
        (self.repo / "app" / "fresh.py").write_text(
            "from app.util import summarize_zones\n\n\n"
            "def again():\n    return summarize_zones({})\n",
            encoding="utf-8")
        self.assertEqual(self.ingest(), self.cold())

    def test_a_tampered_cache_is_never_trusted(self):
        self.ingest()
        con = sqlite3.connect(code_kg.db_path(self.repo))
        self.assertGreater(
            con.execute("SELECT count(*) FROM parse_cache").fetchone()[0], 0)
        con.execute("UPDATE parse_cache SET value = 'not json'")
        con.commit()
        con.close()
        self.assertEqual(self.ingest(), self.cold())

    def test_rows_dropped_behind_its_back_force_a_full_rewrite(self):
        self.ingest()
        con = sqlite3.connect(code_kg.db_path(self.repo))
        con.execute("DELETE FROM symbols WHERE file_id = 'app/util.py'")
        con.commit()
        con.close()
        self.assertEqual(self.ingest(), self.cold())


if __name__ == "__main__":
    unittest.main()

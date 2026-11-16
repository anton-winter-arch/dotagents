"""The session read ledger (`--session` on search, query and read; `reads`
reports it) and search's token budget and per-file cap: markdown-kg's
coverage ledger, budget and diversity, with symbols in place of sections
and files in place of notes. Expected numbers come from the files below."""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_symbol_edges import run  # noqa: E402

import code_kg  # noqa: E402

M = """class Box:
    def open(self):
        a = 1
        return a

    def close(self):
        b = 2
        return b


def helper():
    return 3
"""
N = "def solo():\n    return 4\n"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-reads-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        (self.repo / "m.py").write_text(M, encoding="utf-8")
        (self.repo / "n.py").write_text(N, encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def cli(self, *argv, ok=True):
        rc, out, err = run(argv[0], str(self.repo), *argv[1:], "--json")
        if ok:
            self.assertEqual(rc, 0, err)
            return json.loads(out) if out.strip() else None
        return rc, out, err

    def ledger(self):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute("SELECT session_id, unit_id, file_id, cmd"
                                 " FROM session_reads"))
        con.close()
        return got


class LedgerTests(Case):
    def test_no_session_flag_writes_nothing(self):
        self.cli("search", "return")
        run("read", str(self.repo), "m.py::Box.open")
        self.assertEqual(self.ledger(), [])

    def test_read_query_and_search_record_what_they_return(self):
        run("read", str(self.repo), "m.py::Box.open", "--session", "s1")
        run("read", str(self.repo), "m.py:11-12", "--session", "s1")
        run("read", str(self.repo), "n.py", "--session", "s1")
        self.cli("query", "solo", "--session", "s2")
        hits = self.cli("search", "helper", "--session", "s3")["results"]
        self.assertEqual(self.ledger(), sorted(
            [("s1", "m.py::Box.open", "m.py", "read"),
             ("s1", "m.py::helper", "m.py", "read"),
             ("s1", "n.py", "n.py", "read"),
             ("s2", "n.py", "n.py", "query")]
            + [("s3", h.get("symbol", h["file"]), h["file"], "search")
               for h in hits]))

    def test_first_touch_wins(self):
        run("read", str(self.repo), "n.py", "--session", "s1")
        self.cli("query", "solo", "--session", "s1")
        self.assertEqual(self.ledger(), [("s1", "n.py", "n.py", "read")])

    def test_coverage_of_a_method_read(self):
        run("read", str(self.repo), "m.py::Box.open", "--session", "s1")
        got = self.cli("reads", "--session", "s1")
        self.assertEqual(got["symbols"], {"touched": 1, "total": 5,
                                          "percent": 20.0})
        self.assertEqual(got["lines"], {"touched": 3, "total": 14,
                                        "percent": 21.4})
        self.assertEqual(got["files"], {"touched": 1, "total": 2,
                                        "percent": 50.0})
        self.assertEqual(got["untouched"], [
            {"kind": "symbol", "file_id": "m.py", "symbol_id": "m.py::Box",
             "symbols": 2, "lines": 5},
            {"kind": "symbol", "file_id": "m.py",
             "symbol_id": "m.py::helper", "symbols": 1, "lines": 2},
            {"kind": "file", "file_id": "n.py", "symbols": 1, "lines": 2}])
        self.assertEqual(got["stale"], 0)
        self.assertEqual(got["status"], "COMPLETE")

    def test_a_class_covers_its_methods_and_a_file_covers_all(self):
        run("read", str(self.repo), "m.py::Box", "--session", "s1")
        got = self.cli("reads", "--session", "s1")
        self.assertEqual(got["symbols"]["touched"], 3)
        self.assertEqual(got["lines"]["touched"], 8)
        run("read", str(self.repo), "n.py", "--session", "s1")
        got = self.cli("reads", "--session", "s1")
        self.assertEqual((got["symbols"]["touched"], got["lines"]["touched"],
                          got["files"]["touched"]), (4, 10, 2))

    def test_scope_limit_stale_and_forget(self):
        run("read", str(self.repo), "m.py::helper", "--session", "s1")
        got = self.cli("reads", "--session", "s1", "--scope", "n.py")
        self.assertEqual(got["symbols"]["total"], 1)
        got = self.cli("reads", "--session", "s1", "--limit", "1")
        self.assertEqual(got["status"], "TRUNCATED 1 of 2")
        (self.repo / "m.py").write_text(N.replace("solo", "other"),
                                        encoding="utf-8")
        got = self.cli("reads", "--session", "s1")
        self.assertEqual(got["stale"], 1)
        got = self.cli("reads", "--forget", "s1")
        self.assertEqual(got, {"forgot": "s1", "rows": 1})
        self.assertEqual(self.ledger(), [])

    def test_the_ledger_survives_ingest(self):
        run("read", str(self.repo), "n.py", "--session", "s1")
        run("ingest", str(self.repo))
        self.assertEqual(len(self.ledger()), 1)

    def test_argument_validation(self):
        rc, _, err = self.cli("reads", ok=False)
        self.assertNotEqual(rc, 0)
        rc, _, err = self.cli("reads", "--session", "a", "--forget", "a",
                              ok=False)
        self.assertNotEqual(rc, 0)


class BudgetTests(Case):
    def test_the_budget_is_never_exceeded_and_texts_are_whole(self):
        got = self.cli("search", "return", "--budget", "40")
        self.assertLessEqual(got["spent"], 40)
        self.assertEqual(got["budget"], 40)
        for hit in got["results"]:
            unit = hit.get("symbol", hit["file"])
            rc, out, _ = run("read", str(self.repo), unit)
            self.assertEqual(out.split("\n", 1)[1].rstrip("\n"),
                             hit["text"].rstrip("\n"))

    def test_a_class_too_big_for_the_budget_gives_its_methods(self):
        open_cost = code_kg.est_tokens(
            "\n".join(M.splitlines()[1:4]))
        got = self.cli("search", "Box", "--budget", str(open_cost + 1))
        self.assertEqual([(h["symbol"], h.get("substituted_for"))
                          for h in got["results"]],
                         [("m.py::Box.open", "m.py::Box")])
        self.assertEqual(got["spent"], open_cost)

    def test_budget_reads_go_to_the_ledger(self):
        open_cost = code_kg.est_tokens(
            "\n".join(M.splitlines()[1:4]))
        self.cli("search", "Box", "--budget", str(open_cost + 1),
                 "--session", "s1")
        self.assertEqual([r[1] for r in self.ledger()], ["m.py::Box.open"])

    def test_per_file_cap(self):
        wide = self.cli("search", "return")["results"]
        self.assertGreater(sum(1 for h in wide if h["file"] == "m.py"), 1)
        capped = self.cli("search", "return", "--per-file", "1")["results"]
        files = [h["file"] for h in capped]
        self.assertEqual(len(files), len(set(files)))

    def test_without_the_new_flags_search_is_as_before(self):
        got = self.cli("search", "return")
        self.assertNotIn("budget", got)
        self.assertTrue(all("text" not in h for h in got["results"]))


if __name__ == "__main__":
    unittest.main()

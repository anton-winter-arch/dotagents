"""`related`: files, or symbols, ranked by personalized PageRank from one
seed over the resolved graph, as markdown-kg's `related` ranks notes.
Expected scores are closed forms of the graphs built below."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_symbol_edges import run  # noqa: E402

import code_kg  # noqa: E402

D = code_kg.RELATED_DAMPING


class Case(unittest.TestCase):
    def build(self, files: dict):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-rel-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        for rel, text in files.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def related(self, *argv):
        rc, out, err = run("related", str(self.repo), *argv, "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)


class FileGraphTests(Case):
    def test_two_files_closed_form(self):
        self.build({"a.py": "import b\n", "b.py": "X = 1\n"})
        got = self.related("a.py")
        self.assertEqual(got["graph"], "file")
        self.assertEqual(got["related"], [
            {"id": "b.py", "score": round(D / (1 + D), 6), "hops": 1}])

    def test_a_path_of_three_ranks_by_distance(self):
        self.build({"a.py": "import b\n", "b.py": "import c\n",
                    "c.py": "X = 1\n"})
        got = self.related("a.py")
        self.assertEqual([(r["id"], r["hops"]) for r in got["related"]],
                         [("b.py", 1), ("c.py", 2)])

    def test_parallel_edges_weigh_more(self):
        self.build({"a.py": "import b\nfrom b import X\nimport c\n",
                    "b.py": "X = 1\n", "c.py": "Y = 1\n"})
        got = self.related("a.py")
        self.assertEqual([r["id"] for r in got["related"]], ["b.py", "c.py"])
        self.assertGreater(got["related"][0]["score"],
                           got["related"][1]["score"])

    def test_an_unlinked_file(self):
        self.build({"a.py": "X = 1\n", "b.py": "Y = 1\n"})
        got = self.related("a.py")
        self.assertEqual((got["status"], got["related"]), ("NO_LINKS", []))

    def test_truncation_is_declared_and_ranking_is_stable(self):
        files = {"hub.py": "".join(f"import m{i}\n" for i in range(5))}
        files.update({f"m{i}.py": "X = 1\n" for i in range(5)})
        self.build(files)
        one, two = self.related("hub.py", "--limit", "2"), \
            self.related("hub.py", "--limit", "2")
        self.assertEqual(one, two)
        self.assertEqual(one["status"], "TRUNCATED 2 of 5")
        self.assertEqual(len(self.related("hub.py", "--limit", "0")
                             ["related"]), 5)


class SymbolGraphTests(Case):
    def test_calls_rank_symbols(self):
        self.build({"s.py": "def f():\n    g()\n    g()\n    h()\n\n\n"
                            "def g():\n    pass\n\n\n"
                            "def h():\n    pass\n"})
        got = self.related("s.py::f")
        self.assertEqual(got["graph"], "symbol")
        self.assertEqual([r["id"] for r in got["related"]],
                         ["s.py::g", "s.py::h"])
        self.assertGreater(got["related"][0]["score"],
                           got["related"][1]["score"])

    def test_text_render(self):
        self.build({"a.py": "import b\n", "b.py": "X = 1\n"})
        rc, out, err = run("related", str(self.repo), "a.py")
        self.assertEqual(rc, 0, err)
        self.assertIn("not by content", out)
        self.assertIn("1 hop  b.py", out)


if __name__ == "__main__":
    unittest.main()

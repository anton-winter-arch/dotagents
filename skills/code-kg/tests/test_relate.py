"""`relate` and `relations`: evidence-checked judgments recorded against the
code graph, as markdown-kg's `relate` records them against notes. The quote
is checked where it is cited, the row survives ingest, goes cold when its
anchor changes, and only `--include-inferred` traverses it."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_symbol_edges import run  # noqa: E402

S = """def old_parse(x):
    return x


def new_parse(x):
    # replaces old_parse for every caller
    return x.strip()


def other():
    return 1
"""
NEW, OLD, OTHER = "s.py::new_parse", "s.py::old_parse", "s.py::other"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-relate-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        (self.repo / "s.py").write_text(S, encoding="utf-8")
        (self.repo / "t.py").write_text("import s\n", encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def cli(self, *argv, ok=True):
        rc, out, err = run(argv[0], str(self.repo), *argv[1:], "--json")
        if ok:
            self.assertEqual(rc, 0, err)
            return json.loads(out)
        return rc, err

    def record(self, subject=NEW, obj=OLD, quote="replaces old_parse",
               predicate="replaces"):
        return self.cli("relate", subject, predicate, obj, "--quote", quote)

    def listed(self, *flags):
        return self.cli("relations", *flags)["relations"]


class RelateTests(Case):
    def test_relate_records_verified_evidence(self):
        got = self.record()
        self.assertEqual((got["subject"], got["predicate"], got["object"],
                          got["existing"]), (NEW, "replaces", OLD, False))
        row = self.listed()[0]
        self.assertEqual((row["unit_id"], row["line"], row["quote"],
                          row["status"]),
                         (NEW, 6, "replaces old_parse", "hot"))

    def test_an_unverifiable_quote_is_refused(self):
        rc, err = self.cli("relate", NEW, "replaces", OLD, "--quote",
                           "not in the code", ok=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("quote not found", err)
        rc, err = self.cli("relate", OTHER, "replaces", OLD, "--quote",
                           "replaces old_parse", ok=False)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.listed(), [])

    def test_a_file_can_anchor_and_be_the_object(self):
        got = self.record(subject="t.py", obj="s.py", quote="import s",
                          predicate="wraps")
        self.assertEqual((got["subject"], got["object"]), ("t.py", "s.py"))

    def test_relate_is_idempotent(self):
        one, two = self.record(), self.record()
        self.assertEqual(one["id"], two["id"])
        self.assertTrue(two["existing"])
        self.assertEqual(len(self.listed()), 1)

    def test_it_survives_ingest_and_goes_cold_when_its_anchor_changes(self):
        self.record()
        run("ingest", str(self.repo))
        self.assertEqual(self.listed()[0]["status"], "hot")
        (self.repo / "s.py").write_text(S.replace("x.strip()", "x"),
                                        encoding="utf-8")
        run("ingest", str(self.repo))
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.listed("--include-cold")[0]["status"], "cold")
        (self.repo / "s.py").write_text(S, encoding="utf-8")
        run("ingest", str(self.repo))
        self.assertEqual(self.listed()[0]["status"], "hot")

    def test_traversal_is_opt_in(self):
        self.record()
        plain = self.cli("related", NEW)
        self.assertEqual(plain["status"], "NO_LINKS")
        got = self.cli("related", NEW, "--include-inferred")
        self.assertEqual([r["id"] for r in got["related"]], [OLD])
        callees = self.cli("callees", NEW)["edges"]
        self.assertNotIn("inferred/replaces", [e["kind"] for e in callees])
        callees = self.cli("callees", NEW, "--include-inferred")["edges"]
        row = next(e for e in callees if e["kind"] == "inferred/replaces")
        self.assertEqual((row["dst"], row["provenance"]), (OLD, "inferred"))
        callers = self.cli("callers", OLD, "--include-inferred")["edges"]
        self.assertIn(NEW, [e["src"] for e in callers])

    def test_cold_rows_never_traverse(self):
        self.record()
        (self.repo / "s.py").write_text(S.replace("x.strip()", "x"),
                                        encoding="utf-8")
        got = self.cli("related", NEW, "--include-inferred")
        self.assertEqual(got["status"], "NO_LINKS")

    def test_conflicts_retire_and_resolve(self):
        first = self.record()
        second = self.record(obj=OTHER)
        self.assertEqual(len(second["conflicts"]), 1)
        got = self.cli("relations", "--conflicts")
        self.assertEqual([(c["a"], c["b"], c["state"])
                          for c in got["conflicts"]],
                         [(first["id"], second["id"], "hot")])
        self.assertEqual([r["object"] for r in self.listed("--unit", OTHER)],
                         [OTHER])
        retired = self.cli("relations", "--retire", str(second["id"]))
        self.assertEqual(retired["status"], "retired")
        self.assertEqual([r["id"] for r in self.listed()], [first["id"]])
        run("ingest", str(self.repo))
        statuses = {r["id"]: r["status"]
                    for r in self.listed("--include-cold")}
        self.assertEqual(statuses[second["id"]], "retired")
        seq = got["conflicts"][0]["seq"]
        done = self.cli("relations", "--resolve", str(seq), "kept the first")
        self.assertEqual((done["state"], done["resolution"]),
                         ("cold", "kept the first"))

    def test_text_render(self):
        self.record()
        rc, out, err = run("relations", str(self.repo))
        self.assertEqual(rc, 0, err)
        self.assertIn(f"{NEW} -[replaces]-> {OLD}", out)


if __name__ == "__main__":
    unittest.main()

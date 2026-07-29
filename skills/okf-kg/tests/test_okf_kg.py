#!/usr/bin/env python3
"""Unit + idempotency tests for okf_kg.py. The engine is stdlib-only (enrich
is deferred), so these tests run with a plain `python3 -m unittest`."""
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import okf_kg

FIXTURE = Path(__file__).resolve().parent / "fixture-vault"


class FrontmatterTests(unittest.TestCase):
    def test_inline_list_and_scalars(self):
        text = (
            "---\n"
            "type: decision\n"
            'title: "Quoted Title"\n'
            "tags: [a, b, c-d]\n"
            "timestamp: 2026-05-10\n"
            "---\n\n# Body\n"
        )
        meta, body_start = okf_kg.parse_frontmatter(text)
        self.assertEqual(meta["type"], "decision")
        self.assertEqual(meta["title"], "Quoted Title")
        self.assertEqual(meta["tags"], ["a", "b", "c-d"])
        self.assertEqual(meta["timestamp"], "2026-05-10")
        self.assertEqual(text[body_start:], "\n# Body\n")

    def test_block_list(self):
        text = "---\ntags:\n  - one\n  - two\n---\nbody\n"
        meta, _ = okf_kg.parse_frontmatter(text)
        self.assertEqual(meta["tags"], ["one", "two"])

    def test_no_frontmatter(self):
        meta, body_start = okf_kg.parse_frontmatter("# Just a Heading\n\ntext\n")
        self.assertEqual(meta, {})
        self.assertEqual(body_start, 0)

    def test_unterminated_frontmatter_is_body(self):
        meta, body_start = okf_kg.parse_frontmatter("---\ntype: x\nno closer\n")
        self.assertEqual(meta, {})
        self.assertEqual(body_start, 0)


class LinkTests(unittest.TestCase):
    def test_extracts_internal_skips_external_and_images(self):
        text = (
            "See [a](/knowledge-base/a.md) and [b](b.md) and "
            "[ext](https://example.org/x) and ![img](pic.png) and "
            "[anchor](/knowledge-base/a.md#section)."
        )
        self.assertEqual(
            okf_kg.extract_links(text),
            ["/knowledge-base/a.md", "b.md", "/knowledge-base/a.md"],
        )


class VaultCase(unittest.TestCase):
    """Base: copy the fixture vault into a temp dir per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="okfkg-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        shutil.copytree(FIXTURE, self.vault)

    def db(self):
        return sqlite3.connect(self.vault / okf_kg.DB_NAME)


class IngestTests(VaultCase):
    def test_first_ingest_counts(self):
        report = okf_kg.ingest(self.vault)
        self.assertEqual(report["added"], 6)  # index, log, 4 knowledge-base
        self.assertEqual(report["updated"], 0)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(report["edges"], 10)
        self.assertEqual(report["dangling"], 1)  # reference-fitting-sizes.md

    def test_second_ingest_is_noop(self):
        okf_kg.ingest(self.vault)
        report = okf_kg.ingest(self.vault)
        self.assertEqual(report["added"], 0)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(report["unchanged"], 6)

    def test_concept_fields(self):
        okf_kg.ingest(self.vault)
        row = self.db().execute(
            "SELECT type, title, doc_timestamp, tags FROM concepts WHERE id = ?",
            ("knowledge-base/decisions-drip-vs-sprinkler",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "decision")
        self.assertEqual(row[1], "Drip vs Sprinkler Irrigation")
        self.assertEqual(row[2], "2026-05-10")
        self.assertIn("drip", row[3])

    def test_title_falls_back_to_heading(self):
        okf_kg.ingest(self.vault)
        row = self.db().execute(
            "SELECT title FROM concepts WHERE id = 'log'"
        ).fetchone()
        self.assertEqual(row[0], "Directory Update Log")

    def test_edges_resolve_root_relative_and_relative(self):
        okf_kg.ingest(self.vault)
        edges = set(
            self.db().execute("SELECT src, dst FROM edges WHERE kind = 'link'")
        )
        # root-relative link
        self.assertIn(
            (
                "knowledge-base/runbooks-irrigation-schedule",
                "knowledge-base/architecture-water-system-overview",
            ),
            edges,
        )
        # relative link (decisions -> architecture, sibling file)
        self.assertIn(
            (
                "knowledge-base/decisions-drip-vs-sprinkler",
                "knowledge-base/architecture-water-system-overview",
            ),
            edges,
        )
        # dangling target never becomes an edge
        for _, dst in edges:
            self.assertNotIn("reference-fitting-sizes", dst)

    def test_changed_file_is_updated(self):
        okf_kg.ingest(self.vault)
        f = self.vault / "knowledge-base" / "runbooks-irrigation-schedule.md"
        f.write_text(f.read_text().replace("40 minutes", "45 minutes"))
        report = okf_kg.ingest(self.vault)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(report["added"], 0)
        self.assertEqual(report["unchanged"], 5)

    def test_deleted_file_goes_cold(self):
        okf_kg.ingest(self.vault)
        (self.vault / "knowledge-base" / "meetings-2026-06-15-review.md").unlink()
        report = okf_kg.ingest(self.vault)
        self.assertEqual(report["removed"], 1)
        status = self.db().execute(
            "SELECT status FROM concepts WHERE id = ?",
            ("knowledge-base/meetings-2026-06-15-review",),
        ).fetchone()[0]
        self.assertEqual(status, "cold")

    def test_cli_ingest_runs(self):
        rc = okf_kg.main(["ingest", str(self.vault)])
        self.assertEqual(rc, 0)


class GraphTests(VaultCase):
    def setUp(self):
        super().setUp()
        okf_kg.ingest(self.vault)

    def test_query_finds_body_text(self):
        hits = okf_kg.query(self.vault, "manifold")
        ids = [h["id"] for h in hits]
        self.assertIn("knowledge-base/architecture-water-system-overview", ids)

    def test_query_phrase(self):
        hits = okf_kg.query(self.vault, '"watering interval"')
        ids = {h["id"] for h in hits}
        self.assertIn("knowledge-base/runbooks-irrigation-schedule", ids)
        self.assertIn("knowledge-base/meetings-2026-06-15-review", ids)

    def test_query_invalid_fts_syntax_exits_cleanly(self):
        with self.assertRaises(SystemExit):
            okf_kg.query(self.vault, '"unbalanced phrase')

    def test_query_excludes_cold_concepts(self):
        (self.vault / "knowledge-base" / "meetings-2026-06-15-review.md").unlink()
        okf_kg.ingest(self.vault)
        ids = {h["id"] for h in okf_kg.query(self.vault, '"watering interval"')}
        self.assertNotIn("knowledge-base/meetings-2026-06-15-review", ids)

    def test_neighbors_depth_1(self):
        got = okf_kg.neighbors(
            self.vault, "knowledge-base/architecture-water-system-overview")
        self.assertEqual(
            {n["id"] for n in got},
            {
                "index",
                "knowledge-base/decisions-drip-vs-sprinkler",
                "knowledge-base/runbooks-irrigation-schedule",
            },
        )

    def test_neighbors_depth_2_reaches_meeting(self):
        got = okf_kg.neighbors(
            self.vault, "knowledge-base/architecture-water-system-overview", depth=2)
        by_id = {n["id"]: n["depth"] for n in got}
        self.assertEqual(by_id.get("knowledge-base/meetings-2026-06-15-review"), 2)
        self.assertEqual(by_id.get("log"), 2)

    def test_neighbors_unknown_id_exits(self):
        with self.assertRaises(SystemExit):
            okf_kg.neighbors(self.vault, "no/such-concept")

    def test_path_shortest(self):
        p = okf_kg.path(
            self.vault,
            "knowledge-base/meetings-2026-06-15-review",
            "knowledge-base/decisions-drip-vs-sprinkler",
        )
        # shortest hop is through the index hub
        self.assertEqual(len(p), 3)
        self.assertEqual(p[0], "knowledge-base/meetings-2026-06-15-review")
        self.assertEqual(p[-1], "knowledge-base/decisions-drip-vs-sprinkler")

    def test_path_none_when_disconnected(self):
        orphan = self.vault / "knowledge-base" / "orphan-note.md"
        orphan.write_text("# Orphan Note\n\nNo links here.\n")
        okf_kg.ingest(self.vault)
        p = okf_kg.path(self.vault, "index", "knowledge-base/orphan-note")
        self.assertIsNone(p)

    def test_cli_query_and_traversal(self):
        for argv in (
            ["query", str(self.vault), "manifold"],
            ["neighbors", str(self.vault), "index", "--depth", "2"],
            ["path", str(self.vault), "index", "log"],
        ):
            self.assertEqual(okf_kg.main(argv), 0)


if __name__ == "__main__":
    unittest.main()

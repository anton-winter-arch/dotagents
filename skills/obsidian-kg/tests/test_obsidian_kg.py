#!/usr/bin/env python3
"""Unit + idempotency tests for obsidian_kg.py. The engine is stdlib-only,
so these tests run with a plain `python3 -m unittest`
(`python3 -m unittest discover -s skills/obsidian-kg/tests` from repo root)."""
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import obsidian_kg

FIXTURE = Path(__file__).resolve().parent / "fixture-vault"


class FrontmatterTests(unittest.TestCase):
    def test_inline_list_and_scalars(self):
        text = (
            "---\n"
            'title: "Quoted Title"\n'
            "tags: [a, b, c-d]\n"
            "aliases: [One, Two]\n"
            "priority: 2\n"
            "---\n\n# Body\n"
        )
        meta, body_start = obsidian_kg.parse_frontmatter(text)
        self.assertEqual(meta["title"], "Quoted Title")
        self.assertEqual(meta["tags"], ["a", "b", "c-d"])
        self.assertEqual(meta["aliases"], ["One", "Two"])
        self.assertEqual(meta["priority"], "2")
        self.assertEqual(text[body_start:], "\n# Body\n")

    def test_block_list(self):
        text = "---\ntags:\n  - one\n  - two\n---\nbody\n"
        meta, _ = obsidian_kg.parse_frontmatter(text)
        self.assertEqual(meta["tags"], ["one", "two"])

    def test_no_frontmatter(self):
        meta, body_start = obsidian_kg.parse_frontmatter("# Heading\n\ntext\n")
        self.assertEqual(meta, {})
        self.assertEqual(body_start, 0)


class CodeStrippingTests(unittest.TestCase):
    def test_fenced_block_blanked(self):
        text = "before\n```text\n[[Fenced]]\n```\nafter [[Real]]\n"
        stripped = obsidian_kg.strip_code(text)
        self.assertNotIn("Fenced", stripped)
        self.assertIn("[[Real]]", stripped)

    def test_inline_code_blanked(self):
        stripped = obsidian_kg.strip_code("a `[[Inline]]` b [[Real]]\n")
        self.assertNotIn("Inline", stripped)
        self.assertIn("[[Real]]", stripped)

    def test_tilde_fence(self):
        stripped = obsidian_kg.strip_code("~~~\n[[Hidden]]\n~~~\nok\n")
        self.assertNotIn("Hidden", stripped)
        self.assertIn("ok", stripped)


class LinkExtractionTests(unittest.TestCase):
    def test_wikilink_forms(self):
        text = ("[[Plain]] ![[Embedded]] [[Target#Heading]] "
                "[[Target#Heading|shown text]] [[With|alias]] [[#self only]]")
        self.assertEqual(
            obsidian_kg.extract_wikilinks(text),
            [("Plain", "link"), ("Embedded", "embed"), ("Target", "link"),
             ("Target", "link"), ("With", "link")])

    def test_md_links_skip_images_and_external(self):
        text = ("[a](sub/a.md) [ext](https://example.org/x) ![img](pic.png) "
                '[t](b.md "a title") [frag](c.md#sec)')
        self.assertEqual(obsidian_kg.extract_md_links(text),
                         ["sub/a.md", "b.md", "c.md"])

    def test_md_link_with_space_in_path(self):
        self.assertEqual(
            obsidian_kg.extract_md_links("[p](plans/Garden Plan.md)"),
            ["plans/Garden Plan.md"])


class VaultCase(unittest.TestCase):
    """Base: copy the fixture vault into a temp dir per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="obskg-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        shutil.copytree(FIXTURE, self.vault)

    def db(self):
        return sqlite3.connect(self.vault / obsidian_kg.DB_NAME)


class IngestTests(VaultCase):
    def test_first_ingest_counts(self):
        report = obsidian_kg.ingest(self.vault)
        self.assertEqual(report["notes"], 8)  # .trash/Ghost.md excluded
        self.assertEqual(report["resolved"], 10)
        self.assertEqual(report["unresolved"], 1)   # [[Missing Page]]
        self.assertEqual(report["ambiguous"], 1)    # bare [[Note]]

    def test_ingest_idempotent_row_counts(self):
        obsidian_kg.ingest(self.vault)
        counts1 = self._table_counts()
        report = obsidian_kg.ingest(self.vault)
        self.assertEqual(report["notes"], 8)
        self.assertEqual(self._table_counts(), counts1)

    def test_ingest_deterministic_content(self):
        obsidian_kg.ingest(self.vault)
        dump1 = self._dump()
        obsidian_kg.ingest(self.vault)
        self.assertEqual(self._dump(), dump1)

    def _table_counts(self):
        con = self.db()
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("notes", "properties", "tags", "aliases", "edges")
        }
        con.close()
        return counts

    def _dump(self):
        """Full content of every table except meta (the only timestamp)."""
        con = self.db()
        dump = {
            t: sorted(map(repr, con.execute(f"SELECT * FROM {t}")))
            for t in ("notes", "properties", "tags", "aliases", "edges")
        }
        con.close()
        return dump

    def test_dot_folder_excluded(self):
        obsidian_kg.ingest(self.vault)
        con = self.db()
        rows = [r[0] for r in con.execute("SELECT id FROM notes")]
        con.close()
        self.assertNotIn(".trash/Ghost", rows)
        self.assertFalse(any(r.startswith(".") for r in rows))

    def test_properties_stored(self):
        obsidian_kg.ingest(self.vault)
        con = self.db()
        props = dict(con.execute(
            "SELECT key, value FROM properties WHERE note_id=?",
            ("plans/Garden Plan",)))
        con.close()
        self.assertEqual(props["status"], "draft")
        self.assertEqual(props["priority"], "2")
        self.assertEqual(props["title"], "Garden Plan 2026")
        self.assertNotIn("tags", props)  # normalized into tags table

    def test_title_falls_back_to_heading(self):
        obsidian_kg.ingest(self.vault)
        con = self.db()
        title = con.execute(
            "SELECT title FROM notes WHERE id='Scratch'").fetchone()[0]
        con.close()
        self.assertEqual(title, "Scratch")

    def test_cli_ingest_runs(self):
        self.assertEqual(obsidian_kg.main(["ingest", str(self.vault)]), 0)


class EdgeResolutionTests(VaultCase):
    def setUp(self):
        super().setUp()
        obsidian_kg.ingest(self.vault)

    def edges(self, **where):
        con = self.db()
        sql = "SELECT src, dst, target, syntax, kind, status FROM edges"
        if where:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
        rows = con.execute(sql, tuple(where.values())).fetchall()
        con.close()
        return rows

    def test_bare_wikilink_resolves(self):
        self.assertIn(("Home", "plans/Garden Plan", "Garden Plan",
                       "wiki", "link", "resolved"), self.edges(src="Home"))

    def test_alias_text_wikilink_resolves(self):
        # [[Watering Guide|how to water]] - alias text stripped from target
        self.assertIn(
            ("plans/Garden Plan", "plans/Watering Guide", "Watering Guide",
             "wiki", "link", "resolved"),
            self.edges(src="plans/Garden Plan"))

    def test_heading_wikilink_resolves(self):
        # [[Seed List#Spring]] - heading stripped from target
        self.assertIn(
            ("plans/Garden Plan", "Seed List", "Seed List",
             "wiki", "link", "resolved"),
            self.edges(src="plans/Garden Plan"))

    def test_embed_recorded_as_embed(self):
        self.assertIn(("Home", "Seed List", "Seed List",
                       "wiki", "embed", "resolved"), self.edges(src="Home"))

    def test_md_link_relative_resolution(self):
        # [seeds](../Seed List.md) from plans/ resolves up a directory
        self.assertIn(
            ("plans/Garden Plan", "Seed List", "../Seed List.md",
             "md", "link", "resolved"),
            self.edges(syntax="md"))
        # [full plan](plans/Garden Plan.md) from the vault root
        self.assertIn(
            ("Seed List", "plans/Garden Plan", "plans/Garden Plan.md",
             "md", "link", "resolved"),
            self.edges(syntax="md"))

    def test_frontmatter_alias_resolves_wikilink(self):
        # [[The Plan]] resolves via Garden Plan's aliases: [The Plan]
        self.assertIn(
            ("plans/Watering Guide", "plans/Garden Plan", "The Plan",
             "wiki", "link", "resolved"),
            self.edges(src="plans/Watering Guide"))

    def test_path_qualified_link_beats_collision(self):
        # two Note.md exist; [[projects/Note]] picks by path suffix
        self.assertIn(("Home", "projects/Note", "projects/Note",
                       "wiki", "link", "resolved"), self.edges(src="Home"))

    def test_bare_collision_is_ambiguous_not_guessed(self):
        rows = self.edges(src="Home", target="Note")
        self.assertEqual(rows, [("Home", None, "Note",
                                 "wiki", "link", "ambiguous")])

    def test_unresolved_link_recorded(self):
        rows = self.edges(status="unresolved")
        self.assertEqual(rows, [("Home", None, "Missing Page",
                                 "wiki", "link", "unresolved")])

    def test_fenced_and_inline_code_links_excluded(self):
        targets = {r[2] for r in self.edges()}
        self.assertNotIn("Fenced Target", targets)
        self.assertNotIn("Inline Target", targets)


class QueryTests(VaultCase):
    def setUp(self):
        super().setUp()
        obsidian_kg.ingest(self.vault)

    def test_query_returns_expected_note_first(self):
        hits = obsidian_kg.query(self.vault, "moisture")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "plans/Watering Guide")

    def test_query_phrase(self):
        hits = obsidian_kg.query(self.vault, '"raised beds"')
        self.assertEqual(hits[0]["id"], "plans/Garden Plan")

    def test_query_invalid_fts_syntax_raises(self):
        # Library query() must raise, not sys.exit - it backs a scorer that
        # loops over concept names with FTS5-significant punctuation.
        with self.assertRaises(ValueError):
            obsidian_kg.query(self.vault, '"unbalanced phrase')

    def test_cli_query_runs(self):
        self.assertEqual(obsidian_kg.main(["query", str(self.vault),
                                           "cobalt"]), 0)


class MissingDbTests(VaultCase):
    """Every query command exits nonzero, telling the user to ingest."""

    def test_commands_require_db(self):
        for argv in (
            ["query", str(self.vault), "x"],
            ["note", str(self.vault), "Home"],
            ["backlinks", str(self.vault), "Home"],
            ["links", str(self.vault), "Home"],
            ["neighbors", str(self.vault), "Home"],
            ["path", str(self.vault), "Home", "Scratch"],
            ["tags", str(self.vault)],
            ["stats", str(self.vault)],
        ):
            with self.assertRaises(SystemExit) as cm:
                obsidian_kg.main(argv)
            self.assertTrue(cm.exception.code, msg=argv)
            self.assertIn("ingest", str(cm.exception.code), msg=argv)


class GraphTests(VaultCase):
    def setUp(self):
        super().setUp()
        obsidian_kg.ingest(self.vault)

    def test_backlinks_of_seed_list(self):
        con = self.db()
        rows = set(con.execute(
            "SELECT src, syntax, kind FROM edges WHERE dst='Seed List'"))
        con.close()
        self.assertEqual(rows, {
            ("Home", "wiki", "embed"),
            ("plans/Garden Plan", "wiki", "link"),
            ("plans/Garden Plan", "md", "link"),
        })

    def test_neighbors_depth_1(self):
        got = obsidian_kg.neighbors(self.vault, "Home")
        self.assertEqual(
            {n["id"] for n in got},
            {"plans/Garden Plan", "projects/Note", "Seed List",
             "archive/Note"})

    def test_neighbors_depth_2(self):
        got = obsidian_kg.neighbors(self.vault, "Home", depth=2)
        by_id = {n["id"]: n["depth"] for n in got}
        self.assertEqual(by_id.get("plans/Watering Guide"), 2)
        self.assertEqual(by_id.get("projects/inner/Deep Note"), 2)
        self.assertNotIn("Scratch", by_id)  # orphan, unreachable

    def test_path_shortest(self):
        p = obsidian_kg.path(self.vault, "Home", "Watering Guide")
        self.assertEqual(p, ["Home", "plans/Garden Plan",
                             "plans/Watering Guide"])

    def test_path_none_when_disconnected(self):
        self.assertIsNone(obsidian_kg.path(self.vault, "Home", "Scratch"))

    def test_note_resolves_by_alias(self):
        con = sqlite3.connect(self.vault / obsidian_kg.DB_NAME)
        self.assertEqual(obsidian_kg.resolve_note_arg(con, "The Plan"),
                         "plans/Garden Plan")
        self.assertEqual(obsidian_kg.resolve_note_arg(con, "watering guide"),
                         "plans/Watering Guide")
        con.close()

    def test_note_arg_collision_exits_with_candidates(self):
        con = sqlite3.connect(self.vault / obsidian_kg.DB_NAME)
        with self.assertRaises(SystemExit) as cm:
            obsidian_kg.resolve_note_arg(con, "Note")
        self.assertIn("projects/Note", str(cm.exception.code))
        self.assertIn("archive/Note", str(cm.exception.code))

    def test_cli_note_backlinks_links_run(self):
        for argv in (
            ["note", str(self.vault), "The Plan"],
            ["backlinks", str(self.vault), "Seed List"],
            ["links", str(self.vault), "Home"],
            ["neighbors", str(self.vault), "Home", "--depth", "2"],
            ["path", str(self.vault), "Home", "Watering Guide"],
        ):
            self.assertEqual(obsidian_kg.main(argv), 0, msg=argv)


class TagsStatsTests(VaultCase):
    def setUp(self):
        super().setUp()
        obsidian_kg.ingest(self.vault)

    def test_tag_counts(self):
        con = self.db()
        counts = dict(con.execute(
            "SELECT lower(tag), COUNT(*) FROM tags GROUP BY lower(tag)"))
        con.close()
        self.assertEqual(counts["garden"], 3)
        self.assertEqual(counts["index"], 1)
        self.assertEqual(len(counts), 6)

    def test_tag_filter_lists_notes(self):
        con = self.db()
        rows = [r[0] for r in con.execute(
            "SELECT note_id FROM tags WHERE tag='garden' ORDER BY note_id")]
        con.close()
        self.assertEqual(rows, ["Seed List", "plans/Garden Plan",
                                "plans/Watering Guide"])

    def test_orphan_detection(self):
        con = self.db()
        orphans = [r[0] for r in con.execute(
            "SELECT id FROM notes WHERE id NOT IN"
            " (SELECT src FROM edges WHERE status='resolved')"
            " AND id NOT IN (SELECT dst FROM edges WHERE status='resolved'"
            "                AND dst IS NOT NULL)")]
        con.close()
        self.assertEqual(orphans, ["Scratch"])

    def test_cli_tags_and_stats_run(self):
        for argv in (
            ["tags", str(self.vault)],
            ["tags", str(self.vault), "garden"],
            ["stats", str(self.vault)],
        ):
            self.assertEqual(obsidian_kg.main(argv), 0, msg=argv)

    def test_cli_tags_unknown_tag_nonzero(self):
        self.assertEqual(
            obsidian_kg.main(["tags", str(self.vault), "no-such-tag"]), 1)


if __name__ == "__main__":
    unittest.main()

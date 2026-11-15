#!/usr/bin/env python3
"""Tests for markdown link compatibility, anchors, link fields, inline tags,
derived entities, the `config` check, `related` and `communities`.

Behavior tests run against a temp copy of tests/wiki-fixture-vault: an
LLM-wiki shaped vault (index, log, entity and concept pages, sources) with a
docs-style guides tree that uses standard markdown links."""
import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import markdown_kg as kg

HERE = Path(__file__).resolve().parent
WIKI = HERE / "wiki-fixture-vault"
PLAIN = HERE / "fixture-vault"


def run(*argv: str) -> tuple[int, str, str]:
    """One engine call in-process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = kg.main(list(argv))
        except SystemExit as e:
            if isinstance(e.code, int) or e.code is None:
                rc = e.code or 0
            else:
                rc = 1
                err.write(str(e.code))
    return rc, out.getvalue(), err.getvalue()


# The wiki fixture's config. Written into the temp copy at test time, because
# an engine folder inside a vault is a built index everywhere else and is
# never copied out of this repo, a committed one included.
WIKI_CONFIG = {
    "ignore": [],
    "profiles": [
        {"path": "index.md", "profile": "hub"},
        {"path": "log.md", "profile": "log-dated", "date_from": "heading"},
    ],
    "entities": [
        {"canonical": "Mara Voss", "type": "person", "time": "static",
         "aliases": ["Mara"], "note": "entities/Mara Voss"},
    ],
    "entity_sources": [
        {"path": "entities/*.md", "type": "equipment"},
        {"kg_type": "concept", "type": "concept", "time": "evolving"},
    ],
    "relations": [
        {"field": "blocks"},
        {"field": "fed-by", "inverse": "feeds"},
        {"field": "maintained-by", "inverse": "maintains"},
        {"field": "up", "inverse": "down"},
    ],
}


class VaultCase(unittest.TestCase):
    fixture = WIKI

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mdkg-ext-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        shutil.copytree(self.fixture, self.vault)
        if self.fixture == WIKI:
            cfg_file = kg.config_path(self.vault)
            cfg_file.parent.mkdir(exist_ok=True)
            cfg_file.write_text(kg.dump_config(WIKI_CONFIG), encoding="utf-8")
        run("ingest", str(self.vault))

    def json(self, *argv: str):
        rc, out, err = run(argv[0], str(self.vault), *argv[1:], "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def rows(self, sql: str, *params):
        con = sqlite3.connect(kg.db_path(self.vault))
        out = con.execute(sql, params).fetchall()
        con.close()
        return out

    def note(self, rel: str, text: str) -> None:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def config(self) -> dict:
        return kg.load_config(self.vault)

    def write_config(self, cfg: dict) -> None:
        kg.config_path(self.vault).write_text(
            "```json\n" + json.dumps(cfg) + "\n```\n", encoding="utf-8")

    def limits(self, floor: int) -> None:
        old = kg.WORD_FLOOR
        kg.WORD_FLOOR = floor
        self.addCleanup(setattr, kg, "WORD_FLOOR", old)
        run("ingest", str(self.vault))


# ------------------------------------------------------------------ scanners
class WikilinkScanTests(unittest.TestCase):
    def test_anchor_forms(self):
        text = ("[[Note]] [[Note#Heading]] [[Note#A#B|shown]] [[Note#^blk]] "
                "![[Note#Part]] [[#Local]] [[folder/Note#H\\|alias]]\n")
        self.assertEqual(
            [(t, a, k) for t, a, k, _ in kg.scan_wikilinks(text)],
            [("Note", "", "link"), ("Note", "Heading", "link"),
             ("Note", "A#B", "link"), ("Note", "^blk", "link"),
             ("Note", "Part", "embed"), ("", "Local", "link"),
             ("folder/Note", "H", "link")])

    def test_note_level_view_is_unchanged(self):
        text = "[[A#x]] [[#only-anchor]] ![[B]] `[[C]]`\n"
        self.assertEqual([(t, k) for t, k, _ in kg.extract_wikilinks(text)],
                         [("A", "link"), ("B", "embed")])


class MarkdownLinkScanTests(unittest.TestCase):
    def scan(self, text: str) -> list:
        return [(t, a, s) for t, a, s, _ in kg.scan_md_links(text)]

    def test_inline_forms(self):
        text = ('[a](one.md) [b](two.md#Sec) [c](<three four.md#Big head>) '
                '[d](five.md "a title") [e](#local) ![img](pic.png) '
                '[f](https://example.org/x.md#y) [g](ftp://example.org/y.md)\n')
        self.assertEqual(self.scan(text), [
            ("one.md", "", "inline"), ("two.md", "Sec", "inline"),
            ("three four.md", "Big head", "inline"),
            ("five.md", "", "inline"), ("", "local", "inline")])

    def test_reference_forms(self):
        text = ("See [the guide][guide], [guide][] and [Guide].\n"
                "Not a link: [undefined] or [x] or [text][nowhere].\n\n"
                "[guide]: docs/guide.md#Start\n")
        self.assertEqual(self.scan(text), [
            ("docs/guide.md", "Start", "reference")] * 3)

    def test_reference_edge_cases(self):
        text = ("A footnote[^1] and a [site].\n\n"
                "[^1]: notes.md is only footnote text\n"
                "[site]: https://example.org/page.md\n"
                "[first]: a.md\n[first]: b.md\n\nUse [first].\n")
        self.assertEqual(self.scan(text), [("a.md", "", "reference")])

    def test_code_never_carries_a_link(self):
        text = ("`[a](one.md)`\n\n```\n[b](two.md)\n[c]: three.md\n```\n\n"
                "~~~\n[d][c]\n~~~\n")
        self.assertEqual(self.scan(text), [])

    def test_note_level_view_is_unchanged(self):
        text = "[a](one.md#x) [b](#local) [c][ref]\n\n[ref]: two.md\n"
        self.assertEqual([t for t, _ in kg.extract_md_links(text)],
                         ["one.md"])


class TermSafeTests(unittest.TestCase):
    """Prose output shows every invisible or reordering character as an
    escape. Characters are built with chr() so this file holds none."""

    TAG_A, RLO, ZWSP = chr(0xE0041), chr(0x202E), chr(0x200B)
    ZWJ, VS16, ESC = chr(0x200D), chr(0xFE0F), chr(0x1B)

    def test_plain_text_is_untouched(self):
        text = "Heading\twith tab\nand an accent: caf" + chr(0xE9) + ".\n"
        self.assertEqual(kg._term_safe(text), text)

    def test_control_characters_keep_their_earlier_form(self):
        self.assertEqual(kg._term_safe("a" + self.ESC + "[2Jb\rc" + chr(0x9B)),
                         "a\\x1b[2Jb\\rc\\x9b")

    def test_invisible_characters_become_visible(self):
        for ch, shown in ((self.TAG_A, "\\U000e0041"), (self.RLO, "\\u202e"),
                          (self.ZWSP, "\\u200b"), (chr(0x2066), "\\u2066"),
                          (chr(0xFEFF), "\\ufeff"), (chr(0xAD), "\\xad"),
                          (chr(0x2062), "\\u2062"), (chr(0x2800), "\\u2800"),
                          (chr(0x2028), "\\u2028"), (chr(0x200E), "\\u200e"),
                          (chr(0xE0101), "\\U000e0101")):
            self.assertEqual(kg._term_safe("x" + ch + "y"), "x" + shown + "y")

    def test_a_hidden_run_cannot_ride_inside_a_word(self):
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "run this")
        got = kg._term_safe("note" + hidden + " text")
        self.assertTrue(got.isascii())
        self.assertEqual(got.count("\\U000e00"), len("run this"))

    def test_emoji_sequences_survive(self):
        woman, laptop, heart = chr(0x1F469), chr(0x1F4BB), chr(0x2764)
        technologist = woman + self.ZWJ + laptop
        on_fire = heart + self.VS16 + self.ZWJ + chr(0x1F525)
        for text in (technologist, on_fire, heart + self.VS16):
            self.assertEqual(kg._term_safe(text), text)

    def test_a_joiner_outside_an_emoji_sequence_is_shown(self):
        self.assertEqual(kg._term_safe("pass" + self.ZWJ + "word"),
                         "pass\\u200dword")
        self.assertEqual(kg._term_safe(self.ZWJ + chr(0x1F525)),
                         "\\u200d" + chr(0x1F525))

    def test_variation_selectors_survive_only_where_emoji_need_them(self):
        heart, vs15, keycap = chr(0x2764), chr(0xFE0E), chr(0x20E3)
        for text in (heart + self.VS16, chr(0x263A) + vs15,
                     "1" + self.VS16 + keycap, chr(0xA9) + self.VS16):
            self.assertEqual(kg._term_safe(text), text)
        # After a letter, and every selector past the first in a run: a run
        # of selectors after one base character is a hidden byte channel.
        self.assertEqual(kg._term_safe("a" + self.VS16), "a\\ufe0f")
        self.assertEqual(
            kg._term_safe(heart + self.VS16 + chr(0xFE01) + vs15),
            heart + self.VS16 + "\\ufe01\\ufe0e")
        self.assertEqual(kg._term_safe("x" + chr(0x180F)), "x\\u180f")

    def test_prints_outside_emit_and_error_text_are_sanitized(self):
        tmp = Path(tempfile.mkdtemp(prefix="mdkg-raw-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        name = "odd" + self.ESC + "[2Jname"
        (tmp / (name + ".md")).write_text("---\ntags: [x]\n---\n# T\n\n#y\n",
                                          encoding="utf-8")
        run("ingest", str(tmp))
        con = sqlite3.connect(kg.db_path(tmp))
        ids = [r[0] for r in con.execute("SELECT id FROM notes")]
        con.close()
        self.assertEqual(ids, [name])       # the id keeps the raw character
        for argv in (("tags", str(tmp), "x"),
                     ("tags", str(tmp), "y", "--inline"),
                     ("tags", str(tmp), "x", "--nested")):
            rc, out, _ = run(*argv)
            self.assertEqual(rc, 0, argv)
            self.assertNotIn(self.ESC, out)
            self.assertIn("odd\\x1b[2Jname", out)
        (tmp / "markdown-kg").mkdir(exist_ok=True)
        kg.config_path(tmp).write_text("```json\n" + json.dumps(
            {"entity_sources": [{"path": self.ESC + "]0;x" + chr(7),
                                 "time": "bad"}]}) + "\n```\n",
            encoding="utf-8")
        rc, out, err = run("ingest", str(tmp))
        self.assertEqual(rc, 1)
        self.assertIn("'static' or 'evolving'", err)
        for ch in (self.ESC, chr(7)):
            self.assertNotIn(ch, out + err)

    def test_every_prose_command_goes_through_it(self):
        tmp = Path(tempfile.mkdtemp(prefix="mdkg-safe-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "a.md").write_text(
            "# Top" + self.RLO + "\n\nmaintained-by:: [[b]] #tag\n\n"
            "See [[b#Part" + self.ZWSP + "]].\n", encoding="utf-8")
        (tmp / "b.md").write_text("# B\n\n## Part\n\ntext\n", encoding="utf-8")
        run("ingest", str(tmp))
        for cmd in (("links", "a", "--anchors"), ("fields",), ("sections", "a"),
                    ("fields", "--note", "a"), ("related", "a"),
                    ("communities",), ("config",), ("tags", "--inline"),
                    ("stats",)):
            rc, out, _ = run(cmd[0], str(tmp), *cmd[1:])
            self.assertEqual(rc, 0, cmd)
            for ch in (self.RLO, self.ZWSP):
                self.assertNotIn(ch, out, cmd)


class LinearScanTests(unittest.TestCase):
    """The one-pass link walk must find exactly what MD_LINK_RE finds, and
    must stay linear on input built to make the pattern crawl."""

    def both(self, text: str) -> None:
        want = [(m.start(), m.group(1)) for m in kg.MD_LINK_RE.finditer(text)]
        self.assertEqual(list(kg.iter_md_links(text)), want, repr(text))

    def test_matches_the_pattern_on_awkward_text(self):
        for text in (
                "", "[a](b)", "![a](b)", "x![a](b) [c](d)", "[a [b](c.md)",
                "![a [b](c.md)", "[![alt](img.png)](note.md)", "[a]()",
                "[a](b(c)d)", "[a](b\nc)", "[a\nb](c)", "[a]] (b) [c](d)",
                "[[wiki]](x) [a](b)", "[](x)", "[a](b)[c](d)", "]](a)(b)",
                "[a](b))[c](d)", "!![a](b)", "[!a](b)", "[a](  b  )",
                "[a](<b c.md>)", "](x) [a]", "[a] (b)", "[a](b", "[a]("):
            self.both(text)

    def test_matches_the_pattern_on_generated_text(self):
        import random
        rng = random.Random(20261114)
        for _ in range(4000):
            self.both("".join(rng.choice("[]()!ab \n")
                              for _ in range(rng.randrange(0, 40))))

    def test_title_suffix_matches_the_earlier_pattern(self):
        import re
        old = re.compile(r'^(.*?)\s+"[^"]*"$')
        for raw in ('a.md "t"', 'a.md   "t"', 'a.md "t" "u"', '"a" "b"',
                    'a.md"t"', 'a "b', '"', '""', 'a ""', 'a.md "t" x',
                    'a b.md\t"two words"', ' "only"', 'a.md "t"#frag'):
            target = raw.strip()
            m = old.match(target)
            want = (m.group(1) if m else target).partition("#")[0].strip()
            got = kg._split_md_target(raw)
            self.assertEqual(got[0] if got else None, want, repr(raw))

    def test_adversarial_input_stays_fast(self):
        import time
        hostile = ("[" * 300000,
                   "[x](a" + " " * 300000 + "b)",
                   "[x](a" + " " * 300000 + '"',
                   "[a]" * 100000)
        start = time.time()
        for text in hostile:
            kg.scan_md_links(text)
        # The earlier pattern needed over half a minute for the first one.
        self.assertLess(time.time() - start, 5.0)


class ResolveMdNoteTests(unittest.TestCase):
    IDS = ["concepts/Gravity Feed", "entities/Cistern", "guides/Notes",
           "guides/setup", "guides/sub/deep", "index", "sources/Notes"]

    def resolve(self, target: str, src: str = "guides/setup.md",
                ignored: set = frozenset(), vault_wide: bool = True):
        return kg.resolve_md_note(target, src, self.IDS, set(self.IDS),
                                  set(ignored), kg._index_by_base(self.IDS),
                                  vault_wide)

    def test_relative_mode_never_reads_a_link_vault_wide(self):
        for target in ("Cistern.md", "Notes.md"):
            self.assertEqual(self.resolve(target, "index.md",
                                          vault_wide=False),
                             (None, "unresolved"))
        self.assertIsNone(self.resolve("Cistern", vault_wide=False))
        # The plain relative forms are the same in both modes.
        self.assertEqual(self.resolve("../entities/Cistern", vault_wide=False),
                         ("entities/Cistern", "resolved"))
        self.assertEqual(self.resolve("sub/deep.md", vault_wide=False),
                         ("guides/sub/deep", "resolved"))

    def test_relative_and_root_paths(self):
        self.assertEqual(self.resolve("sub/deep.md"),
                         ("guides/sub/deep", "resolved"))
        self.assertEqual(self.resolve("../entities/Cistern.md"),
                         ("entities/Cistern", "resolved"))
        self.assertEqual(self.resolve("/index.md"), ("index", "resolved"))
        self.assertEqual(self.resolve("../concepts/Gravity%20Feed.md"),
                         ("concepts/Gravity Feed", "resolved"))

    def test_relative_wins_over_the_fallback(self):
        # guides/Notes exists beside the source, so the basename is not
        # ambiguous from here.
        self.assertEqual(self.resolve("Notes.md"),
                         ("guides/Notes", "resolved"))

    def test_obsidian_shortest_path_and_vault_path(self):
        self.assertEqual(self.resolve("Cistern.md"),
                         ("entities/Cistern", "resolved"))
        self.assertEqual(self.resolve("entities/Cistern.md",
                                      "guides/sub/deep.md"),
                         ("entities/Cistern", "resolved"))
        self.assertEqual(self.resolve("Notes.md", "index.md"),
                         (None, "ambiguous"))

    def test_extensionless(self):
        self.assertEqual(self.resolve("../entities/Cistern"),
                         ("entities/Cistern", "resolved"))
        self.assertEqual(self.resolve("Cistern"),
                         ("entities/Cistern", "resolved"))
        # Names no note: a site route or a folder, never a broken link.
        self.assertIsNone(self.resolve("/docs/intro"))
        self.assertIsNone(self.resolve("nowhere"))

    def test_an_explicit_path_never_falls_back(self):
        self.assertEqual(self.resolve("./Cistern.md"), (None, "unresolved"))
        self.assertEqual(self.resolve("/Cistern.md"), (None, "unresolved"))
        self.assertIsNone(self.resolve("./Cistern"))

    def test_not_a_note(self):
        self.assertIsNone(self.resolve("levels.csv"))
        self.assertIsNone(self.resolve("../../outside.md"))
        self.assertIsNone(self.resolve("../../Cistern.md"))

    def test_missing_and_ignored(self):
        self.assertEqual(self.resolve("gone.md"), (None, "unresolved"))
        self.assertEqual(self.resolve("archive.md", ignored={"guides/archive"}),
                         (None, "ignored"))


class AnchorTests(unittest.TestCase):
    TEXT = ("---\ntitle: T\n---\n# Top\n\n## Part One\n\ntext ^first-block\n\n"
            "## **Bold** part\n\n### Inner\n\n- item\n\n^list-block\n\n"
            "## Part One\n\n```\n## Not A Heading\ncode ^not-a-block\n```\n\n"
            "## Other\n\n### Inner\n")

    def setUp(self):
        self.index = kg.anchor_index(self.TEXT)

    def line(self, anchor: str):
        at = kg.resolve_anchor(self.index, anchor)
        return at[1] if at else None

    def test_slug(self):
        self.assertEqual(kg.heading_slug("Order of work"), "order-of-work")
        self.assertEqual(kg.heading_slug("What's new? (v2.1)"),
                         "whats-new-v21")
        self.assertEqual(kg.heading_slug("snake_case and-dash"),
                         "snake_case-and-dash")

    def test_exact_and_case_insensitive(self):
        self.assertEqual(self.line("Part One"), 6)
        self.assertEqual(self.line("part   one"), 6)

    def test_plain_text_match(self):
        self.assertEqual(self.line("Bold part"), 10)

    def test_slug_and_repeat_suffix(self):
        self.assertEqual(self.line("part-one"), 6)
        self.assertEqual(self.line("part-one-1"), 18)
        self.assertEqual(self.line("bold-part"), 10)

    def test_heading_path(self):
        self.assertEqual(self.line("Bold part#Inner"), 12)
        self.assertEqual(self.line("Other#Inner"), 27)
        self.assertEqual(self.line("Inner"), 12)        # first in the note
        self.assertIsNone(self.line("Part One#Inner"))

    def test_blocks(self):
        self.assertEqual(self.line("^first-block"), 8)
        self.assertEqual(self.line("^LIST-BLOCK"), 16)
        self.assertIsNone(self.line("^not-a-block"))

    def test_missing(self):
        self.assertIsNone(self.line("Not A Heading"))
        self.assertIsNone(self.line("nope"))
        self.assertIsNone(self.line(""))


class FieldScanTests(unittest.TestCase):
    def scan(self, text: str) -> list:
        return [(f, o, s, t) for f, o, s, t, _ in kg.scan_field_links(text)]

    def test_frontmatter_forms(self):
        text = ('---\nup: "[[Parent]]"\nrelated:\n  - "[[A]]"\n  - "[[B|b]]"\n'
                "source: [[Raw#Sec]]\nspec: \"[doc](docs/spec.md#x)\"\n"
                "tags: [\"[[NotAField]]\"]\naliases: [[Nor This]]\n"
                "Mixed-Case: \"[[C]]\"\nplain: text\n---\nbody\n")
        self.assertEqual(self.scan(text), [
            ("up", "frontmatter", "wiki", "Parent"),
            ("related", "frontmatter", "wiki", "A"),
            ("related", "frontmatter", "wiki", "B"),
            ("source", "frontmatter", "wiki", "Raw"),
            ("spec", "frontmatter", "md", "docs/spec.md"),
            ("mixed-case", "frontmatter", "wiki", "C")])

    def test_inline_forms(self):
        text = ("up:: [[Parent]]\n- feeds:: [[A]], [[B]]\n"
                "> Depends On:: [[C]]\n1. step:: [doc](d.md)\n"
                "Text with [part-of:: [[D]]] and (see:: [[E]]) inside.\n")
        self.assertEqual(self.scan(text), [
            ("up", "inline", "wiki", "Parent"),
            ("feeds", "inline", "wiki", "A"), ("feeds", "inline", "wiki", "B"),
            ("depends-on", "inline", "wiki", "C"),
            ("step", "inline", "md", "d.md"),
            ("part-of", "inline", "wiki", "D"),
            ("see", "inline", "wiki", "E")])

    def test_what_is_not_a_field(self):
        text = ("status:: draft\nA sentence with [[Link]] and a::b.\n"
                "`up:: [[Code]]`\n\n```\nup:: [[Fenced]]\n```\n\n"
                "%%\nup:: [[Hidden]]\n%%\n\n<!--\nup:: [[Commented]]\n-->\n")
        self.assertEqual(self.scan(text), [])

    def test_an_overlong_line_is_skipped(self):
        text = "up:: " + "[[A]] " * 3000 + "\n"
        self.assertEqual(self.scan(text), [])


class InlineTagScanTests(unittest.TestCase):
    def tags(self, text: str) -> list:
        return [t for t, _ in kg.scan_inline_tags(text)]

    def test_tag_rules(self):
        text = ("---\ntags: [front]\n---\n# Heading\n\n"
                "Words #plain and #nested/child/ and #with_under-dash.\n"
                "#line-start then #2026 and #12a and #é-accent\n"
                "| cell #in-table |\n")
        self.assertEqual(self.tags(text), [
            "plain", "nested/child", "with_under-dash", "line-start", "12a",
            "é-accent", "in-table"])

    def test_what_is_not_a_tag(self):
        text = ("# Heading #\n\nA url https://example.org/#frag and "
                "[link](#anchor) and [[#Heading]] and word#glued.\n"
                "`#code` and C# and #!/bin/sh\n\n```\n#fenced\n```\n\n"
                "%%\n#hidden\n%%\n")
        self.assertEqual(self.tags(text), [])


# ------------------------------------------------- markdown links and anchors
class WikiVaultLinkTests(VaultCase):
    def edge(self, src: str, target: str):
        got = self.rows("SELECT status, dst FROM edges WHERE src=?"
                        " AND target=?", src, target)
        self.assertEqual(len(got), 1, f"{src} -> {target}: {got}")
        return got[0]

    def test_ingest_counts(self):
        rc, out, _ = run("ingest", str(self.vault))
        self.assertEqual(rc, 0)
        self.assertIn("50 resolved, 1 unresolved, 1 ambiguous", out)
        self.assertIn("3 non-note targets skipped", out)

    def test_standard_relative_links(self):
        for target, dst in (
                ("maintenance.md", "guides/maintenance"),
                ("sub/deep.md", "guides/sub/deep"),
                ("../entities/Cistern.md", "entities/Cistern"),
                ("../entities/Rill Pump.md", "entities/Rill Pump"),
                ("../concepts/Gravity Feed.md", "concepts/Gravity Feed")):
            self.assertEqual(self.edge("guides/setup", target),
                             ("resolved", dst))
        self.assertEqual(self.edge("guides/maintenance", "/index.md"),
                         ("resolved", "index"))

    def test_obsidian_style_markdown_links(self):
        self.assertEqual(self.edge("guides/setup", "Cistern.md"),
                         ("resolved", "entities/Cistern"))
        self.assertEqual(self.edge("guides/setup", "concepts/Gravity Feed.md"),
                         ("resolved", "concepts/Gravity Feed"))
        self.assertEqual(self.edge("guides/setup", "../concepts/Drip Irrigation"),
                         ("resolved", "concepts/Drip Irrigation"))
        self.assertEqual(self.edge("guides/sub/deep", "entities/Cistern.md"),
                         ("resolved", "entities/Cistern"))

    VAULT_WIDE = (("guides/setup", "Cistern.md"),
                  ("guides/setup", "concepts/Gravity Feed.md"),
                  ("guides/sub/deep", "entities/Cistern.md"))

    def test_link_mode_is_detected_from_the_obsidian_folder(self):
        self.assertEqual(self.json("config")["link_resolution"],
                         {"mode": "obsidian", "source": "detected .obsidian/"})
        shutil.rmtree(self.vault / ".obsidian")
        self.assertEqual(self.json("config")["link_resolution"],
                         {"mode": "relative", "source": "default"})
        # Removing the folder is drift: the next read re-resolved the links.
        for src, target in self.VAULT_WIDE:
            self.assertEqual(self.edge(src, target), ("unresolved", None))
        self.assertEqual(self.edge("guides/sub/deep", "Notes.md"),
                         ("unresolved", None))
        # An exact relative path with no extension is not a vault-wide read.
        self.assertEqual(self.edge("guides/setup", "../concepts/Drip Irrigation"),
                         ("resolved", "concepts/Drip Irrigation"))

    def test_config_overrides_detection(self):
        cfg = self.config()
        cfg["link_resolution"] = "relative"
        self.write_config(cfg)
        self.assertEqual(self.json("config")["link_resolution"],
                         {"mode": "relative", "source": "config"})
        for src, target in self.VAULT_WIDE:
            self.assertEqual(self.edge(src, target), ("unresolved", None))
        shutil.rmtree(self.vault / ".obsidian")
        cfg["link_resolution"] = "obsidian"
        self.write_config(cfg)
        self.assertEqual(self.json("config")["link_resolution"]["source"],
                         "config")
        for src, target in self.VAULT_WIDE:
            self.assertEqual(self.edge(src, target)[0], "resolved")

    def test_link_resolution_is_validated(self):
        cfg = self.config()
        cfg["link_resolution"] = "loose"
        self.write_config(cfg)
        rc, _, err = run("ingest", str(self.vault))
        self.assertEqual(rc, 1)
        self.assertIn("'link_resolution' must be", err)

    def test_reference_links_become_edges(self):
        self.assertEqual(self.edge("guides/setup", "../sources/site-survey.md"),
                         ("resolved", "sources/site-survey"))
        self.assertEqual(
            self.edge("entities/Rill Pump", "../sources/2026-04 Pump Manual.md"),
            ("resolved", "sources/2026-04 Pump Manual"))

    def test_broken_and_ambiguous_stay_on_the_worklist(self):
        got = {(e["src"], e["target"], e["status"])
               for e in self.json("links", "--unresolved")}
        self.assertEqual(got, {
            ("guides/setup", "missing-note.md", "unresolved"),
            ("guides/sub/deep", "Notes.md", "ambiguous")})

    def test_non_notes_and_fenced_links_make_no_edge(self):
        targets = {r[0] for r in self.rows(
            "SELECT target FROM edges WHERE src IN"
            " ('guides/setup', 'guides/sub/deep')")}
        for bad in ("levels.csv", "/docs/intro", "diagram.png",
                    "../../../elsewhere.md", "../entities/Mara Voss.md",
                    "Mara Voss"):
            self.assertNotIn(bad, targets)
        self.assertFalse(any("example.org" in t for t in targets))

    def test_backlinks_see_both_syntaxes(self):
        got = {(e["src"], e["syntax"])
               for e in self.json("backlinks", "Cistern")}
        self.assertLessEqual({("guides/setup", "md"), ("guides/sub/deep", "md"),
                              ("entities/Rill Pump", "wiki"),
                              ("entities/Header Tank", "wiki")}, got)


class AnchorCommandTests(VaultCase):
    def anchors(self, *argv: str) -> dict:
        return {(e["syntax"], e["target"], e["anchor"]): e
                for e in self.json(*argv, "--anchors")}

    def test_every_anchor_form_from_one_note(self):
        got = self.anchors("links", "guides/setup")
        want = {
            ("md", "sub/deep.md", "Deep-topic"): ("resolved", 1),
            ("md", "../entities/Cistern.md", "capacity"): ("resolved", 15),
            ("md", "../entities/Rill Pump.md", "Flow rate"): ("resolved", 11),
            ("md", "../concepts/Gravity Feed.md", "friction-loss"):
                ("resolved", 16),
            ("md", "../entities/Cistern.md", "^overflow-note"):
                ("resolved", 23),
            ("wiki", "Drip Irrigation", "Bold layout"): ("resolved", 13),
            ("wiki", "Drip Irrigation", "Emitters"): ("resolved", 9),
            ("md", "", "checks"): ("resolved", 13),
            ("md", "maintenance.md", "checks-1"): ("resolved", 13),
            ("md", "maintenance.md", "no-such-heading"): ("anchor-missing", 0),
            ("md", "concepts/Gravity Feed.md", "Head height"): ("resolved", 10),
            ("md", "../sources/site-survey.md", "Levels"): ("resolved", 8),
        }
        self.assertEqual({k: (e["status"], e["dst_line"])
                          for k, e in got.items()}, want)

    def test_dst_line_is_the_heading_or_block_line(self):
        got = self.anchors("links", "guides/setup")
        for key, rel in (
                (("md", "../entities/Cistern.md", "capacity"),
                 "entities/Cistern.md"),
                (("md", "maintenance.md", "checks-1"),
                 "guides/maintenance.md")):
            line = (self.vault / rel).read_text().splitlines()[
                got[key]["dst_line"] - 1]
            self.assertTrue(line.startswith("## "), line)
        block = got[("md", "../entities/Cistern.md", "^overflow-note")]
        self.assertEqual((self.vault / "entities/Cistern.md").read_text()
                         .splitlines()[block["dst_line"] - 1],
                         "^overflow-note")

    def test_same_note_anchor_points_at_its_own_section(self):
        got = self.anchors("links", "guides/setup")[("md", "", "checks")]
        self.assertEqual(got["dst"], "guides/setup")
        self.assertEqual(got["dst_section"], "guides/setup#Setup > Checks")
        wiki = self.anchors("links", "Gravity Feed")[("wiki", "", "Head height")]
        self.assertEqual((wiki["dst"], wiki["status"]),
                         ("concepts/Gravity Feed", "resolved"))

    def test_nested_heading_path_and_block_in_wikilinks(self):
        got = self.anchors("links", "Drip Irrigation")
        self.assertEqual(got[("wiki", "Gravity Feed", "Limits#Friction loss")]
                         ["dst_line"], 16)
        tank = self.anchors("links", "Header Tank")
        self.assertEqual(tank[("wiki", "Cistern", "^overflow-note")]
                         ["dst_line"], 23)

    def test_a_small_floor_gives_each_heading_its_own_section(self):
        self.limits(floor=1)
        got = self.anchors("links", "guides/setup")
        self.assertEqual(
            got[("md", "../entities/Cistern.md", "capacity")]["dst_section"],
            "entities/Cistern#Cistern > Capacity")
        self.assertEqual(
            got[("md", "../concepts/Gravity Feed.md", "friction-loss")]
            ["dst_section"],
            "concepts/Gravity Feed#Gravity Feed > Limits > Friction loss")
        self.assertEqual(
            got[("md", "maintenance.md", "checks-1")]["dst_section"],
            "guides/maintenance#Maintenance > Checks~1")

    def test_worklist_is_the_missing_anchors_only(self):
        rows = self.json("links", "--unresolved", "--anchors")
        self.assertEqual([(e["src"], e["target"], e["anchor"], e["status"])
                          for e in rows],
                         [("guides/setup", "maintenance.md", "no-such-heading",
                           "anchor-missing")])

    def test_inbound_anchors(self):
        rows = self.json("backlinks", "Cistern", "--anchors")
        self.assertEqual(
            sorted((e["src"], e["anchor"], e["dst_line"]) for e in rows),
            [("entities/Header Tank", "^overflow-note", 23),
             ("guides/setup", "^overflow-note", 23),
             ("guides/setup", "capacity", 15),
             ("guides/sub/deep", "Capacity", 15)])

    def test_links_anchors_needs_a_note(self):
        rc, _, err = run("links", str(self.vault), "--anchors")
        self.assertEqual(rc, 1)
        self.assertIn("needs a note", err)

    def test_anchor_on_an_unresolved_note_keeps_the_note_status(self):
        self.note("extra.md", "[[Nowhere#Part]] and [x](Notes.md#Part)\n")
        got = {(e["target"], e["status"])
               for e in self.json("links", "extra", "--anchors")}
        self.assertEqual(got, {("Nowhere", "unresolved"),
                               ("Notes.md", "ambiguous")})

    def test_text_render(self):
        rc, out, _ = run("links", str(self.vault), "guides/setup", "--anchors")
        self.assertEqual(rc, 0)
        self.assertIn("ANCHOR-MISSING  (as 'maintenance.md' #"
                      " 'no-such-heading')", out)
        self.assertIn("(line 15)  (as '../entities/Cistern.md' # 'capacity')",
                      out)


# --------------------------------------------------------------- link fields
class FieldCommandTests(VaultCase):
    def test_summary(self):
        got = {r["field"]: r for r in self.json("fields")["fields"]}
        self.assertEqual({f: r["links"] for f, r in got.items()},
                         {"feeds": 2, "maintained-by": 2, "related": 2,
                          "fed-by": 1, "see-also": 1, "source": 1, "spec": 1,
                          "up": 1, "blocks": 0})
        self.assertEqual(got["maintained-by"]["inverse"], "maintains")
        self.assertTrue(got["blocks"]["declared"])
        self.assertFalse(got["feeds"]["declared"])

    def test_one_field(self):
        got = self.json("fields", "--field", "Maintained By")
        self.assertEqual(got["field"], "maintained-by")
        self.assertEqual([(e["src"], e["dst"], e["origin"])
                          for e in got["links"]],
                         [("entities/Cistern", "entities/Mara Voss", "inline"),
                          ("entities/Rill Pump", "entities/Mara Voss",
                           "inline")])

    def test_one_note_both_directions(self):
        got = self.json("fields", "--note", "Mara Voss")
        self.assertEqual([(e["field"], e["dst"]) for e in got["out"]],
                         [("see-also", "entities/Rill Pump")])
        self.assertEqual([(e["src"], e["field"], e["inverse"])
                          for e in got["in"]],
                         [("entities/Cistern", "maintained-by", "maintains"),
                          ("entities/Rill Pump", "maintained-by",
                           "maintains")])

    def test_frontmatter_markdown_link_is_a_field(self):
        got = self.json("fields", "--field", "spec")["links"]
        self.assertEqual([(e["target"], e["dst"], e["origin"]) for e in got],
                         [("../sources/site-survey.md", "sources/site-survey",
                           "frontmatter")])

    def test_field_links_are_ordinary_edges_too(self):
        edges = {(s, d) for s, d in self.rows(
            "SELECT src, dst FROM edges WHERE status='resolved'")}
        for src, dst in self.rows(
                "SELECT src, dst FROM link_fields WHERE status='resolved'"):
            self.assertIn((src, dst), edges)

    def test_unresolved_field_target(self):
        self.note("extra.md", "depends-on:: [[Nowhere]]\n")
        got = self.json("fields", "--field", "depends-on")["links"]
        self.assertEqual([(e["target"], e["status"], e["dst"]) for e in got],
                         [("Nowhere", "unresolved", None)])

    def test_text_render(self):
        rc, out, _ = run("fields", str(self.vault), "--note", "Mara Voss")
        self.assertEqual(rc, 0)
        self.assertIn("maintains  <-  entities/Cistern  [inline]", out)
        rc, out, _ = run("fields", str(self.vault))
        self.assertIn("maintained-by  2 resolved in 2 notes"
                      "  (inverse: maintains)", out)


# --------------------------------------------------------------- inline tags
class InlineTagCommandTests(VaultCase):
    def test_plain_tags_output_is_frontmatter_only(self):
        self.assertEqual(self.json("tags"), [
            {"count": 4, "tag": "entity"}, {"count": 2, "tag": "concept"},
            {"count": 2, "tag": "source"}, {"count": 1, "tag": "person"},
            {"count": 1, "tag": "water/pump"},
            {"count": 1, "tag": "water/storage"}])

    def test_inline_counts(self):
        got = {r["tag"]: (r["count"], r["frontmatter"], r["inline"])
               for r in self.json("tags", "--inline")}
        self.assertEqual(got["maintenance"], (2, 0, 2))
        self.assertEqual(got["water/pump"], (2, 1, 1))
        # Frontmatter and body in the same note: one note, counted once.
        self.assertEqual(got["water/storage"], (1, 1, 1))
        self.assertEqual(got["q2-review"], (1, 0, 1))
        for absent in ("hidden-tag", "not-a-tag", "2026"):
            self.assertNotIn(absent, got)

    def test_notes_for_a_tag(self):
        self.assertEqual(self.json("tags", "maintenance", "--inline"),
                         ["guides/maintenance", "log"])
        rc, out, _ = run("tags", str(self.vault), "maintenance")
        self.assertEqual(rc, 1)           # frontmatter only: nobody has it

    def test_nested(self):
        self.assertEqual(self.json("tags", "water", "--nested"),
                         ["entities/Cistern", "entities/Rill Pump"])
        self.assertEqual(self.json("tags", "#water", "--nested", "--inline"),
                         ["entities/Cistern", "entities/Rill Pump",
                          "guides/maintenance"])
        rc, _, _ = run("tags", str(self.vault), "water")
        self.assertEqual(rc, 1)           # a parent is not its children

    def test_section_is_recorded(self):
        self.assertEqual(
            self.rows("SELECT section_id, tag, count FROM inline_tags"
                      " WHERE note_id='log'"),
            [("log#Log > [2026-05-20] lint | Links", "maintenance", 1)])


# ---------------------------------------------------------- derived entities
class EntitySourceTests(VaultCase):
    def test_derived_and_explicit_entities(self):
        self.assertEqual(self.rows(
            "SELECT canonical, type, time, note, origin FROM entities"
            " ORDER BY canonical"), [
            ("Cistern", "equipment", "static", "entities/Cistern", "note"),
            ("Drip Irrigation", "concept", "evolving",
             "concepts/Drip Irrigation", "note"),
            ("Gravity Feed", "concept", "evolving", "concepts/Gravity Feed",
             "note"),
            ("Header Tank", "equipment", "static", "entities/Header Tank",
             "note"),
            ("Mara Voss", "person", "static", "entities/Mara Voss", "config"),
            ("Rill Pump", "equipment", "static", "entities/Rill Pump",
             "note")])

    def test_frontmatter_aliases_fold_in(self):
        self.assertEqual(
            [r[0] for r in self.rows("SELECT alias FROM entity_aliases WHERE"
                                     " canonical='Cistern' ORDER BY alias")],
            ["Cistern", "Rain tank", "Tank"])

    def test_skipped_names_are_recorded_not_fatal(self):
        rc, _, _ = run("ingest", str(self.vault))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(
            "SELECT note_id, name, reason FROM entity_skips ORDER BY 1"), [
            ("entities/Header Tank", "Tank", "claimed by 'Cistern'"),
            ("entities/Mara Voss", "Mara Voss",
             "an entities row already names this note"),
            ("entities/Rill Pump", "RP", "shorter than 3 characters")])

    def test_entity_command_resolves_a_derived_alias(self):
        got = self.json("entity", "rain tank")
        self.assertEqual(got["canonical"], "Cistern")
        self.assertEqual(got["note"], "entities/Cistern")
        sections = {m["section_id"] for m in got["mentions"]}
        self.assertIn("log#Log > [2026-05-02] ingest | Site Survey", sections)

    def test_timeline_on_a_derived_entity(self):
        got = self.json("timeline", "Header Tank")
        self.assertEqual([m["doc_date"] for m in got["mentions"]],
                         ["2026-05-02"])

    def test_a_derived_canonical_collision_skips_the_second_note(self):
        self.note("entities/Twin.md", "---\ntitle: Cistern\n---\nA twin.\n")
        rc, _, _ = run("ingest", str(self.vault))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(
            "SELECT name, reason FROM entity_skips WHERE note_id=?",
            "entities/Twin"), [("Cistern", "claimed by 'Cistern'")])
        self.assertEqual(self.rows(
            "SELECT note FROM entities WHERE canonical='Cistern'"),
            [("entities/Cistern",)])

    def test_explicit_alias_beats_a_derived_name(self):
        cfg = self.config()
        cfg["entities"].append({"canonical": "Water Store",
                                "aliases": ["Rain tank"]})
        self.write_config(cfg)
        run("ingest", str(self.vault))
        self.assertEqual(self.json("entity", "Rain tank")["canonical"],
                         "Water Store")
        self.assertIn(("entities/Cistern", "Rain tank",
                       "claimed by 'Water Store'"),
                      self.rows("SELECT * FROM entity_skips"))

    def test_without_the_key_nothing_is_derived(self):
        cfg = self.config()
        cfg["entity_sources"] = []
        self.write_config(cfg)
        run("ingest", str(self.vault))
        self.assertEqual(self.rows("SELECT canonical FROM entities"),
                         [("Mara Voss",)])
        self.assertEqual(self.rows("SELECT * FROM entity_skips"), [])

    def test_row_shape_is_validated(self):
        good = self.config()
        for bad, fragment in (
                ({"path": "a/*.md", "kg_type": "x"}, "exactly one"),
                ({}, "exactly one"),
                ({"path": "a/*.md", "time": "2026-01-01..2026-02-01"},
                 "'static' or 'evolving'")):
            cfg = dict(good)
            cfg["entity_sources"] = [bad]
            self.write_config(cfg)
            rc, _, err = run("ingest", str(self.vault))
            self.assertEqual(rc, 1)
            self.assertIn(fragment, err)


class RelationsConfigTests(VaultCase):
    def test_validation(self):
        good = self.config()
        for bad, fragment in (
                ({"field": "Up"}, "must be lowercase"),
                ({"field": "up", "inverse": "Has Child"}, "must be lowercase"),
                ({"field": "tags"}, "reserved property"),
                ({}, "must be lowercase")):
            cfg = dict(good)
            cfg["relations"] = [bad]
            self.write_config(cfg)
            rc, _, err = run("ingest", str(self.vault))
            self.assertEqual(rc, 1, bad)
            self.assertIn(fragment, err)
        cfg = dict(good)
        cfg["relations"] = [{"field": "up"}, {"field": "up"}]
        self.write_config(cfg)
        self.assertIn("declared twice", run("ingest", str(self.vault))[2])

    def test_dump_round_trips_the_extension_keys(self):
        cfg = self.config()
        text = kg.dump_config(cfg)
        kg.config_path(self.vault).write_text(text, encoding="utf-8")
        again = self.config()
        self.assertEqual(again["entity_sources"], cfg["entity_sources"])
        self.assertEqual(again["relations"], cfg["relations"])

    def test_dump_omits_the_keys_when_empty(self):
        text = kg.dump_config({"ignore": [], "profiles": [], "entities": []})
        self.assertNotIn("entity_sources", text)
        self.assertNotIn("relations", text)


# -------------------------------------------------------------- config check
class ConfigCommandTests(VaultCase):
    def test_report(self):
        got = self.json("config")
        self.assertEqual(got["path"], "markdown-kg/markdown-kg-config.md")
        self.assertEqual(got["status"], "WARNINGS")
        self.assertEqual(got["warnings"], [
            "3 derived entity names were left out (see skipped)",
            "relations field is never used: blocks"])
        self.assertEqual(got["profiles"], [
            {"match": "index.md", "profile": "hub", "matched": 1},
            {"match": "log.md", "profile": "log-dated", "matched": 1}])
        self.assertEqual(got["entity_sources"], [
            {"match": "entities/*.md", "type": "equipment", "matched": 4,
             "derived": 3},
            {"match": "kg_type concept", "type": "concept", "matched": 2,
             "derived": 2}])
        self.assertEqual(got["derived_entities"], 5)
        self.assertEqual([s["name"] for s in got["skipped"]],
                         ["Tank", "Mara Voss", "RP"])
        self.assertEqual({r["field"]: r["links"] for r in got["relations"]},
                         {"blocks": 0, "fed-by": 1, "maintained-by": 2,
                          "up": 1})
        self.assertEqual([r["field"] for r in got["undeclared_fields"]],
                         ["feeds", "related", "see-also", "source", "spec"])

    def test_rows_that_match_nothing(self):
        cfg = self.config()
        cfg["ignore"].append({"path": "attic/**"})
        cfg["profiles"].append({"path": "journal.md", "profile": "log-dated"})
        cfg["entities"].append({"canonical": "Nobody Mentioned"})
        cfg["entity_sources"].append({"path": "people/*.md"})
        self.write_config(cfg)
        warnings = self.json("config")["warnings"]
        for want in ("ignore row matched nothing: attic/**",
                     "profiles row matched nothing: journal.md",
                     "entity is never mentioned: Nobody Mentioned",
                     "entity_sources row matched nothing: people/*.md"):
            self.assertIn(want, warnings)

    def test_unknown_profile_name_is_flagged(self):
        cfg = self.config()
        cfg["profiles"].append({"path": "log.md", "profile": "log-date"})
        self.write_config(cfg)
        self.assertIn("profiles row names an unknown profile: 'log-date'"
                      " (log.md)", self.json("config")["warnings"])

    def test_writes_nothing(self):
        before = kg.config_path(self.vault).read_bytes()
        files = sorted(p.name for p in self.vault.rglob("*.md"))
        run("config", str(self.vault))
        self.assertEqual(kg.config_path(self.vault).read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.vault.rglob("*.md")),
                         files)

    def test_text_render(self):
        rc, out, _ = run("config", str(self.vault))
        self.assertEqual(rc, 0)
        self.assertIn("markdown-kg/markdown-kg-config.md: WARNINGS", out)
        self.assertIn("entity source entities/*.md: 4 notes, 3 entities", out)
        self.assertIn("skipped 'RP' from entities/Rill Pump", out)


class ConfigCommandNoConfigTests(VaultCase):
    fixture = PLAIN

    def test_a_vault_with_no_config_is_ok(self):
        got = self.json("config")
        self.assertFalse(got["exists"])
        self.assertEqual(got["status"], "OK")
        self.assertEqual(got["warnings"], [])


# ------------------------------------------------------------------- related
class RelatedTests(VaultCase):
    D = kg.RELATED_DAMPING

    def synthetic(self, notes: dict) -> None:
        shutil.rmtree(self.vault)
        self.vault.mkdir()
        for name, text in notes.items():
            self.note(name, text)
        run("ingest", str(self.vault))

    def scores(self, seed: str, *argv: str) -> dict:
        return {r["id"]: r["score"]
                for r in self.json("related", seed, *argv)["related"]}

    def test_two_notes_closed_form(self):
        # p_a = (1 - d) + d * p_b and p_b = d * p_a, so p_b = d / (1 + d).
        self.synthetic({"a.md": "[[b]]\n", "b.md": "text\n"})
        self.assertAlmostEqual(self.scores("a")["b"], self.D / (1 + self.D),
                               places=5)

    def test_path_of_three_closed_form(self):
        # a - b - c, seed a: p_c = d * p_b / 2, p_b = d * (p_a + p_c),
        # p_a = (1 - d) + d * p_b / 2.
        self.synthetic({"a.md": "[[b]]\n", "b.md": "[c](c.md)\n",
                        "c.md": "end\n"})
        d = self.D
        p_b = d * (1 - d) / (1 - d * d)
        got = self.scores("a")
        self.assertAlmostEqual(got["b"], p_b, places=5)
        self.assertAlmostEqual(got["c"], d * p_b / 2, places=5)

    def test_two_paths_outrank_one(self):
        # Both x and y are two hops from the seed; x is reached through two
        # intermediate notes, y through one.
        self.synthetic({"seed.md": "[[m1]] [[m2]] [[m3]]\n",
                        "m1.md": "[[x]]\n", "m2.md": "[[x]]\n",
                        "m3.md": "[[y]]\n", "x.md": "x\n", "y.md": "y\n"})
        got = self.json("related", "seed")["related"]
        by_id = {r["id"]: r for r in got}
        self.assertEqual(by_id["x"]["hops"], 2)
        self.assertEqual(by_id["y"]["hops"], 2)
        self.assertGreater(by_id["x"]["score"], by_id["y"]["score"])

    def test_parallel_links_weigh_more(self):
        self.synthetic({"seed.md": "[[a]] ![[a]] [a](a.md) [[b]]\n",
                        "a.md": "a\n", "b.md": "b\n"})
        got = self.scores("seed")
        self.assertGreater(got["a"], got["b"])

    def test_hubs_are_left_out(self):
        got = self.scores("Cistern", "--limit", "-1")
        self.assertNotIn("index", got)
        self.assertIn("entities/Rill Pump", got)

    def test_a_hub_can_still_be_the_seed(self):
        got = self.json("related", "index", "--limit", "-1")
        self.assertEqual(got["status"], "COMPLETE")
        self.assertIn("entities/Cistern", {r["id"] for r in got["related"]})

    def test_unlinked_note(self):
        got = self.json("related", "guides/Notes")
        self.assertEqual((got["status"], got["related"]), ("NO_LINKS", []))

    def test_truncation_is_declared_and_ranking_is_stable(self):
        first = self.json("related", "Cistern", "--limit", "3")
        self.assertEqual(first["status"], "TRUNCATED 3 of 11")
        self.assertEqual(first, self.json("related", "Cistern", "--limit", "3"))
        scores = [r["score"] for r in first["related"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_unresolved_and_ambiguous_links_carry_no_weight(self):
        got = self.scores("guides/sub/deep", "--limit", "-1")
        self.assertNotIn("guides/Notes", got)
        self.assertNotIn("sources/Notes", got)

    def test_text_render(self):
        rc, out, _ = run("related", str(self.vault), "Cistern")
        self.assertEqual(rc, 0)
        self.assertIn("not by content", out)
        self.assertIn("1 hop  entities/Rill Pump", out)


# --------------------------------------------------------------- communities
class CommunityTests(VaultCase):
    def synthetic(self, notes: dict) -> None:
        shutil.rmtree(self.vault)
        self.vault.mkdir()
        for name, text in notes.items():
            (self.vault / name).write_text(text, encoding="utf-8")
        run("ingest", str(self.vault))

    def test_two_cliques_and_a_bridge(self):
        notes = {}
        for group in ("a", "b"):
            for i in range(1, 5):
                links = " ".join(f"[[{group}{j}]]" for j in range(1, 5)
                                 if j != i)
                notes[f"{group}{i}.md"] = links + "\n"
        notes["a1.md"] += "[[b1]]\n"
        notes["alone.md"] = "no links\n"
        self.synthetic(notes)
        got = self.json("communities")
        self.assertEqual([c["notes"] for c in got["communities"]],
                         [["a1", "a2", "a3", "a4"], ["b1", "b2", "b3", "b4"]])
        self.assertEqual(got["unplaced"], ["alone"])
        self.assertGreater(got["modularity"], 0.3)
        self.assertEqual([c["external_edges"] for c in got["communities"]],
                         [1, 1])

    def test_wiki_fixture(self):
        got = self.json("communities")
        self.assertEqual(got["hubs"], ["index"])
        self.assertEqual(got["unplaced"], ["guides/Notes", "sources/Notes"])
        placed = [n for c in got["communities"] for n in c["notes"]]
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(len(placed), 12)
        self.assertNotIn("index", placed)

    def test_no_links_at_all(self):
        self.synthetic({"a.md": "one\n", "b.md": "two\n"})
        got = self.json("communities")
        self.assertEqual((got["communities"], got["modularity"]), ([], 0.0))
        self.assertEqual(got["unplaced"], ["a", "b"])

    def test_text_render(self):
        rc, out, _ = run("communities", str(self.vault))
        self.assertEqual(rc, 0)
        self.assertIn("modularity", out)
        self.assertIn("hubs, left out (1):", out)


def reference_greedy_modularity(adj: dict, deg: dict, m: float) -> dict:
    """The clustering with one table of every link, rescanned on each merge:
    correct and slow. Kept here as the answer key the engine's neighbor-map
    version must reproduce exactly."""
    import heapq
    if m <= 0:
        return {}
    comm = {n: i for i, n in enumerate(sorted(adj))}
    members = {i: {n} for n, i in comm.items()}
    tot = {comm[n]: deg[n] for n in adj}
    link = {}
    for a, nbrs in adj.items():
        for b, w in nbrs.items():
            ca, cb = comm[a], comm[b]
            if ca != cb:
                link[(ca, cb) if ca < cb else (cb, ca)] = w

    def gain(ca, cb):
        w = link.get((ca, cb) if ca < cb else (cb, ca), 0.0)
        return w / m - (tot[ca] * tot[cb]) / (2.0 * m * m)

    heap = [(-gain(a, b), a, b) for a, b in link]
    heapq.heapify(heap)
    while heap:
        negdq, ca, cb = heapq.heappop(heap)
        if ca not in members or cb not in members:
            continue
        if ((ca, cb) if ca < cb else (cb, ca)) not in link:
            continue
        fresh = gain(ca, cb)
        if abs(fresh - (-negdq)) > 1e-12:
            heapq.heappush(heap, (-fresh, ca, cb))
            continue
        if fresh <= 1e-12:
            break
        keep, drop = (ca, cb) if ca < cb else (cb, ca)
        members[keep] |= members.pop(drop)
        tot[keep] += tot.pop(drop)
        for n in members[keep]:
            comm[n] = keep
        for k in [k for k in link if drop in k]:
            w = link.pop(k)
            other = k[0] if k[1] == drop else k[1]
            if other != keep:
                nk = (keep, other) if keep < other else (other, keep)
                link[nk] = link.get(nk, 0.0) + w
        for k in list(link):
            if keep in k:
                other = k[0] if k[1] == keep else k[1]
                heapq.heappush(heap, (-gain(keep, other), keep, other))
    return comm


def random_graph(rng, nodes: int, edges: int):
    """Symmetric weighted adjacency in the shape `_note_graph` builds."""
    names = [f"n{i:05d}" for i in range(nodes)]
    adj = {}
    for _ in range(edges):
        a, b = rng.choice(names), rng.choice(names)
        if a == b:
            continue
        w = float(rng.randint(1, 3))
        adj.setdefault(a, {})
        adj.setdefault(b, {})
        adj[a][b] = adj[a].get(b, 0.0) + w
        adj[b][a] = adj[a][b]
    deg = {n: sum(w.values()) for n, w in adj.items()}
    return adj, deg, sum(deg.values()) / 2.0


def star_graph(leaves: int):
    """One hub linked to every leaf, unit weights. The hub sorts last."""
    hub = "zz-hub"
    adj = {hub: {}}
    for i in range(leaves):
        leaf = f"leaf{i:05d}"
        adj[hub][leaf] = 1.0
        adj[leaf] = {hub: 1.0}
    deg = {n: sum(w.values()) for n, w in adj.items()}
    return adj, deg, sum(deg.values()) / 2.0


class ClusteringEquivalenceTests(unittest.TestCase):
    def test_same_groups_on_stars_and_tie_heavy_graphs(self):
        """An index note without the hub profile is a star, and it is where
        a merge queue that keeps its stale entries grows fastest. Unit
        weights make every gain a tie, which is where a change in the order
        entries leave the queue would show."""
        import random
        rng = random.Random(11)
        graphs = [star_graph(n) for n in (2, 3, 7, 25, 60)]
        for _ in range(150):
            nodes = rng.randint(3, 30)
            adj, deg, m = star_graph(nodes)
            names = sorted(adj)
            for _ in range(rng.randint(0, nodes)):
                a, b = rng.sample(names, 2)
                adj[a][b] = adj[b][a] = 1.0
            deg = {n: sum(w.values()) for n, w in adj.items()}
            graphs.append((adj, deg, sum(deg.values()) / 2.0))
        for adj, deg, m in graphs:
            self.assertEqual(kg._greedy_modularity(adj, deg, m),
                             reference_greedy_modularity(adj, deg, m))

    def test_a_star_clusters_quickly(self):
        import time
        adj, deg, m = star_graph(1000)
        start = time.time()
        got = kg._greedy_modularity(adj, deg, m)
        # A queue that re-queues every stale entry needs minutes here.
        self.assertLess(time.time() - start, 5.0)
        self.assertEqual(len(got), 1001)

    def test_same_groups_as_the_reference_on_random_graphs(self):
        import random
        rng = random.Random(20261114)
        for _ in range(400):
            nodes = rng.randint(2, 45)
            adj, deg, m = random_graph(rng, nodes, rng.randint(1, nodes * 3))
            got = kg._greedy_modularity(adj, deg, m)
            want = reference_greedy_modularity(adj, deg, m)
            self.assertEqual(got, want)
            self.assertEqual(list(got), list(want))

    def test_a_large_graph_clusters_quickly(self):
        import random
        import time
        adj, deg, m = random_graph(random.Random(7), 4000, 20000)
        start = time.time()
        got = kg._greedy_modularity(adj, deg, m)
        # The reference needs several seconds here.
        self.assertLess(time.time() - start, 2.0)
        self.assertEqual(set(got), set(adj))


# ------------------------------------------------------------- compatibility
class UpgradeTests(VaultCase):
    def test_a_database_from_before_the_new_tables_upgrades_on_read(self):
        con = sqlite3.connect(kg.db_path(self.vault))
        for table in ("anchors", "link_fields", "inline_tags", "entity_skips",
                      "entities"):
            con.execute(f"DROP TABLE {table}")
        con.execute(
            "CREATE TABLE entities(canonical TEXT PRIMARY KEY, type TEXT NOT"
            " NULL DEFAULT '', time TEXT NOT NULL DEFAULT 'static', note TEXT"
            " NOT NULL DEFAULT '', t_start TEXT NOT NULL DEFAULT '', t_end"
            " TEXT NOT NULL DEFAULT '')")
        con.execute("UPDATE meta SET value='stale' WHERE key='manifest'")
        con.commit()
        con.close()
        self.assertEqual(len(self.json("links", "guides/setup", "--anchors")),
                         12)
        self.assertEqual(self.json("config")["derived_entities"], 5)

    def test_revision_bump_reingests(self):
        con = sqlite3.connect(kg.db_path(self.vault))
        con.execute("DELETE FROM link_fields")
        con.commit()
        con.close()
        self.assertEqual(self.json("fields")["fields"][0]["links"], 0)
        old = kg.INDEX_REV
        self.addCleanup(setattr, kg, "INDEX_REV", old)
        kg.INDEX_REV = old + 1
        self.assertEqual(self.json("fields")["fields"][0]["links"], 2)

    def test_ingest_report_has_no_new_keys(self):
        report = self.json("ingest")
        self.assertEqual(sorted(report), [
            "ambiguous", "annotations", "bad_profiles", "entities",
            "ignored_files", "ignored_links", "mentions", "notes", "resolved",
            "sections", "skipped_assets", "unresolved"])


if __name__ == "__main__":
    unittest.main()

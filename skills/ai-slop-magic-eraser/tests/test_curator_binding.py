#!/usr/bin/env python3
"""Contract tests for the eraser-to-curator binding - stdlib only.

    python3 -m unittest discover skills/ai-slop-magic-eraser/tests

The binding is two files agreeing with each other: the skill forks into the
`curator` agent, and the agent preloads the skill. Both must say that meaning is
fixed. A model reads these files, so the tests pin the sentences that carry the
contract rather than any behavior a script could run.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SKILL_MD = SKILL / "SKILL.md"
CURATOR_MD = SKILL.parent.parent / "agents" / "curator.md"


def frontmatter(path: Path) -> dict:
    """Top-level keys of a YAML frontmatter block, with simple lists."""
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    fields: dict = {}
    key = None
    for line in match.group(1).splitlines():
        item = re.match(r"\s+-\s+(.*)", line)
        if item and key:
            fields.setdefault(key, []).append(item.group(1).strip())
            continue
        pair = re.match(r"([A-Za-z_-]+):\s*(.*)", line)
        if pair:
            key = pair.group(1)
            fields[key] = pair.group(2).strip().strip('"') or []
    return fields


def body(path: Path) -> str:
    """The file after its frontmatter, with whitespace collapsed."""
    text = re.sub(r"\A---\n.*?\n---\n", "", path.read_text(encoding="utf-8"), flags=re.S)
    return " ".join(text.split())


class EraserForksIntoCurator(unittest.TestCase):
    def test_frontmatter_forks_into_the_curator_agent(self):
        fields = frontmatter(SKILL_MD)
        self.assertEqual(fields.get("context"), "fork")
        self.assertEqual(fields.get("agent"), "curator")

    def test_states_that_meaning_is_fixed(self):
        text = body(SKILL_MD)
        self.assertIn("meaning is fixed", text.lower())
        self.assertIn("never adds a claim, drops one, softens one or strengthens one", text)

    def test_a_fact_survives_a_tone_rule(self):
        text = body(SKILL_MD)
        self.assertIn("When a tone rule and a fact collide", text)
        self.assertIn("the fact wins", text)
        self.assertIn("never dropped and flagged", text)

    def test_no_rule_cuts_an_unverified_claim(self):
        for path in (SKILL_MD, SKILL / "references" / "tells.md"):
            text = body(path)
            self.assertNotIn("Unverified is cut", text, path.name)
            self.assertIn("never cuts it", text, path.name)

    def test_pass_two_flags_and_never_edits(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertIn("## Pass 2: check", text)
        self.assertNotIn("## Pass 2: correct", text)
        self.assertIn("**Flags**", text)
        self.assertNotIn("**Corrections**", text)


@unittest.skipUnless(CURATOR_MD.is_file(), "agents/curator.md is not beside this skill")
class CuratorPreloadsTheEraser(unittest.TestCase):
    def test_preloads_the_eraser(self):
        self.assertIn("ai-slop-magic-eraser", frontmatter(CURATOR_MD).get("skills", []))

    def test_tool_allowlist_is_exact_and_holds_no_shell(self):
        tools = {t.strip() for t in frontmatter(CURATOR_MD)["tools"].split(",")}
        self.assertEqual(tools, {"Read", "Grep", "Glob", "Edit"})

    def test_frontmatter_is_out_of_scope(self):
        self.assertIn("Frontmatter is out of scope", body(CURATOR_MD))

    def test_model_is_pinned(self):
        self.assertEqual(frontmatter(CURATOR_MD).get("model"), "opus")

    def test_states_that_meaning_is_fixed(self):
        text = body(CURATOR_MD)
        self.assertIn("Meaning is fixed", text)
        self.assertIn("never add a claim, drop one, soften one or strengthen one", text)

    def test_a_fact_survives_a_tone_rule(self):
        text = body(CURATOR_MD)
        self.assertIn("When a tone rule and a fact collide", text)
        self.assertIn("the fact wins", text)
        self.assertIn("never drop it and flag the loss", text)


if __name__ == "__main__":
    unittest.main()

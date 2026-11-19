#!/usr/bin/env python3
"""lib/ holds code several skills share; a skill that imports it says so.

A skill ships standalone unless its SKILL.md frontmatter carries
`metadata.ships: repo-lib`, which means it needs this repo's lib/ folder beside
its skills/ folder. This test holds the marker to the code both ways: a skill
whose scripts import a lib/ module must carry the marker and a `compatibility`
line naming lib/, and a skill carrying the marker must import one. A module
that imports from lib/ must not also define a name the lib/ module exports,
since that copy is how the two drifted apart before.

Run: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"
LIB_MODULES = {p.stem for p in LIB.glob("*.py")}


def frontmatter(skill_md: Path) -> list[str]:
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    end = next((i for i, line in enumerate(lines[1:], 1)
                if line.strip() == "---"), 0)
    return lines[1:end]


def ships(lines: list[str]) -> str | None:
    """`metadata.ships`, read from the indented block under `metadata:`."""
    in_metadata = False
    for line in lines:
        if not line.startswith((" ", "\t")):
            in_metadata = line.rstrip() == "metadata:"
            continue
        m = re.match(r"\s+ships:\s*['\"]?([\w-]+)", line)
        if in_metadata and m:
            return m.group(1)
    return None


def lib_imports(tree: ast.Module) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name in LIB_MODULES}
        elif isinstance(node, ast.ImportFrom) and node.module in LIB_MODULES:
            out.add(node.module)
    return out


def exported(module: str) -> set[str]:
    tree = ast.parse((LIB / f"{module}.py").read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return {n for n in names if not n.startswith("_")}


def skill_scripts(skill: Path) -> list[Path]:
    return [p for p in skill.rglob("*.py")
            if "tests" not in p.relative_to(skill).parts]


class RepoLibTests(unittest.TestCase):
    def test_the_ships_marker_matches_the_imports(self):
        for skill_md in sorted(ROOT.glob("skills/*/SKILL.md")):
            skill = skill_md.parent
            used = set()
            for script in skill_scripts(skill):
                used |= lib_imports(ast.parse(script.read_text(encoding="utf-8")))
            lines = frontmatter(skill_md)
            marked = ships(lines) == "repo-lib"
            with self.subTest(skill=skill.name):
                self.assertEqual(marked, bool(used),
                                 f"imports {sorted(used) or 'nothing'} from lib/"
                                 f" but ships is {ships(lines)!r}")
                if used:
                    compat = next((ln for ln in lines
                                   if ln.startswith("compatibility:")), "")
                    self.assertIn("lib/", compat)

    def test_no_importer_redefines_a_lib_name(self):
        for script in sorted(ROOT.glob("skills/*/scripts/*.py")):
            tree = ast.parse(script.read_text(encoding="utf-8"))
            mine = {n.name for n in tree.body
                    if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
            for module in lib_imports(tree):
                with self.subTest(script=script.relative_to(ROOT).as_posix()):
                    self.assertEqual(sorted(mine & exported(module)), [])


if __name__ == "__main__":
    unittest.main()

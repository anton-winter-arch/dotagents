#!/usr/bin/env python3
"""Every script outside app/ runs on the station's python3, which on stock macOS is 3.9.

A 3.10 union annotation (`str | None`) is evaluated when the def runs unless the module
starts with `from __future__ import annotations`, so on 3.9 the import itself raises
TypeError. A hook that crashes on import exits 1, which the harness treats as a pass,
so the guard does nothing and looks healthy. This test parses every tracked Python file
and fails on a union annotation without the future import, a `match` statement, or a
top-level `import tomllib`. Run on 3.9 it also fails on any file that does not parse
there. app/ declares its own floor in pyproject.toml.
Run: python3 -m unittest discover -s tests
"""

import ast
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXEMPT = ("app/", "skills-archive/")


def tracked_python():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if not p.startswith(EXEMPT)]


def annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    yield a.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def has_union(annotation):
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation))


def future_annotations(tree):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)


def problems(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"line {e.lineno}: does not parse on this interpreter"]
    found = []
    if not future_annotations(tree):
        found += [f"line {a.lineno}: union annotation without the future import"
                  for a in annotations(tree) if has_union(a)][:1]
    found += [f"line {n.lineno}: match statement" for n in ast.walk(tree)
              if type(n).__name__ == "Match"][:1]
    found += [f"line {n.lineno}: top-level import tomllib" for n in tree.body
              if isinstance(n, ast.Import) and any(a.name == "tomllib" for a in n.names)]
    return found


class TestPythonFloor(unittest.TestCase):
    def test_every_script_imports_on_3_9(self):
        failures = []
        for rel in tracked_python():
            failures += [f"{rel} {p}" for p in problems((ROOT / rel).read_text(encoding="utf-8"))]
        self.assertEqual(failures, [], "\n" + "\n".join(failures))

    def test_the_check_sees_what_it_claims(self):
        self.assertTrue(problems("def f(x: str | None): pass\n"))
        self.assertTrue(problems("x: int | None = None\n"))
        self.assertTrue(problems("import tomllib\n"))
        self.assertTrue(problems("match x:\n    case 1:\n        pass\n"))
        self.assertFalse(problems("from __future__ import annotations\ndef f(x: str | None): pass\n"))
        self.assertFalse(problems("def f():\n    import tomllib\n"))
        self.assertFalse(problems("flags = A | B\n"))


if __name__ == "__main__":
    unittest.main()

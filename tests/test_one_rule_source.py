#!/usr/bin/env python3
"""The sanitize skill's detect.py is the one rule source: no other scanner holds a content
pattern or a codepoint table of its own.

Each caller is loaded and every compiled regex it holds at module level is tried against
content-shaped probes (a key, an email, a home path, a work item, a role code, a catalog
name, a hidden character). A prose pattern (a fence, a bullet, a shell variable) matches
none of them; a content pattern that crept back would. Each caller must also reach the
engine. Probes are joined at runtime, so this file's source holds none of the shapes.
Run: python3 -m unittest discover -s tests
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETECT = ROOT / "skills" / "sanitize" / "scripts"
CALLERS = {
    "closeout_lint": ROOT / "skills" / "wrap-up" / "scripts" / "closeout_lint.py",
    "unicode_smuggle_check": ROOT / "skills" / "my-security-review-checklist" / "scripts" / "unicode_smuggle_check.py",
    "reject_invisibles": ROOT / "hooks" / "reject_invisibles.py",
    "reject_identifiers": ROOT / "hooks" / "reject_identifiers.py",
    "scan_body": ROOT / "skills" / "agent-mail" / "scripts" / "scan_body.py",
}
PROBES = [
    "sk_live_" + "Ab3dEf6hIj9kLm2nOp5q", "someone" + "@" + "real-domain.io", "/" + "Users/qwertz/x",
    "STORY-" + "583920", "AB (" + "PM1)", "prod" + "_gold", "a" + chr(0x202E) + "b", "a" + chr(0x200B) + "b",
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(f"caller_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestOneRuleSource(unittest.TestCase):
    def test_no_caller_holds_a_content_pattern(self):
        for name, path in CALLERS.items():
            module = load(name, path)
            for attr, value in vars(module).items():
                if isinstance(value, re.Pattern) and value is not getattr(module, "detect", object()):
                    hits = [p for p in PROBES if value.search(p)]
                    # a pattern borrowed from the engine is the engine's, not a copy
                    borrowed = any(value is v for v in vars(sys.modules["detect"]).values()
                                   if isinstance(v, re.Pattern)) if "detect" in sys.modules else False
                    self.assertTrue(borrowed or not hits, f"{name}.{attr} matches content probes {hits}")

    def test_every_caller_reaches_the_engine(self):
        for name, path in CALLERS.items():
            source = path.read_text(encoding="utf-8")
            self.assertIn("detect", source, f"{name} does not reference the engine")
            self.assertNotIn("unicodedata.category", source, f"{name} classifies codepoints itself")

    def test_the_engine_is_where_callers_expect_it(self):
        self.assertTrue((DETECT / "detect.py").is_file())


if __name__ == "__main__":
    unittest.main()

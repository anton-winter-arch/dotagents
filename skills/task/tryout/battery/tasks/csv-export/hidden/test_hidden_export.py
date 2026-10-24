import subprocess
import sys
import unittest

from app.export import to_csv


def main(*args):
    return subprocess.run([sys.executable, "-m", "app.main", *args], capture_output=True, text=True)


class TestHiddenExport(unittest.TestCase):
    def test_csv_output(self):
        r = main("--format", "csv")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "zone,flow\nnorth,3\nsouth,5\ntotal,8\n")

    def test_default_and_json_unchanged(self):
        for args in ((), ("--format", "json")):
            r = main(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, '{"zones": 2, "total": 8}\n')

    def test_unknown_format_fails(self):
        self.assertNotEqual(main("--format", "xml").returncode, 0)

    def test_quoting(self):
        self.assertEqual(to_csv([("a,b", 1), ('say "hi"', 2), ("plain", 3)]),
                         '"a,b",1\n"say ""hi""",2\nplain,3\n')

    def test_empty(self):
        self.assertEqual(to_csv([]), "")

    def test_readme_documents_the_option(self):
        with open("README.md", encoding="utf-8") as fh:
            self.assertIn("--format", fh.read())

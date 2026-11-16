"""`tree` in markdown-kg: every file in the vault by folder, notes and the
attachments no parser reads, in the same shape code-kg's `tree` gives.
Expected counts come from the vault built below."""
import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import markdown_kg as kg  # noqa: E402

VAULT = {
    "index.md": "# Index\n\nSee [[a]].\n",
    "notes/a.md": "# A\n\nline\n",
    "notes/deep/b.md": "# B\n",
    "notes/img.png": "\x89PNG\r\n",
    "notes/deep/data.csv": "a,b\n",
    "files/README": "no extension\n",
    ".obsidian/app.json": "{}\n",
}


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = kg.main(list(argv))
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
            if isinstance(e.code, str):
                err.write(e.code)
    return rc, out.getvalue(), err.getvalue()


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mkg-tree-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vault = self.tmp / "vault"
        for rel, text in VAULT.items():
            p = self.vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        rc, _, err = run("ingest", str(self.vault))
        self.assertEqual(rc, 0, err)

    def json(self, *argv):
        rc, out, err = run(argv[0], str(self.vault), *argv[1:], "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def test_attachments_are_inventoried_and_never_notes(self):
        con = sqlite3.connect(kg.db_path(self.vault))
        others = sorted(con.execute("SELECT path, ext, reason FROM"
                                    " other_files"))
        notes = sorted(r[0] for r in con.execute("SELECT id FROM notes"))
        con.close()
        self.assertEqual(others, [("files/README", "", "no-parser"),
                                  ("notes/deep/data.csv", ".csv",
                                   "no-parser"),
                                  ("notes/img.png", ".png", "no-parser")])
        self.assertEqual(notes, ["index", "notes/a", "notes/deep/b"])

    def test_folders_tally_every_file(self):
        got = self.json("tree")
        rows = {f["path"]: f for f in got["folders"]}
        self.assertEqual(sorted(rows), ["", "files", "notes", "notes/deep"])
        self.assertEqual((rows[""]["files"], rows[""]["total"]), (1, 6))
        self.assertEqual(rows[""]["languages"], {"markdown": 3})
        self.assertEqual(rows[""]["other"], {"(none)": 1, ".csv": 1,
                                             ".png": 1})
        self.assertEqual((rows["notes"]["files"], rows["notes"]["total"]),
                         (2, 4))
        self.assertEqual(got["root"], str(self.vault))
        self.assertEqual(got["status"], "COMPLETE")

    def test_files_depth_and_absolute(self):
        got = self.json("tree", "notes", "--depth", "1", "--files",
                        "--absolute")
        self.assertEqual([f["path"] for f in got["folders"]], ["notes"])
        files = {f["path"]: f for f in got["files"]}
        self.assertEqual(sorted(files), ["notes/a.md", "notes/img.png"])
        self.assertEqual(files["notes/a.md"]["language"], "markdown")
        self.assertEqual(files["notes/a.md"]["absolute"],
                         str(self.vault / "notes" / "a.md"))

    def test_a_new_attachment_is_drift(self):
        (self.vault / "notes" / "b.pdf").write_text("%PDF", encoding="utf-8")
        got = self.json("tree", "notes", "--depth", "1")
        # Folder rows count recursively: data.csv sits in notes/deep.
        self.assertEqual(got["folders"][0]["other"],
                         {".csv": 1, ".pdf": 1, ".png": 1})

    def test_text_render_and_cut(self):
        rc, out, err = run("tree", str(self.vault), "--files", "--limit",
                           "2")
        self.assertEqual(rc, 0, err)
        self.assertIn("status: TRUNCATED 2 of 4", out)
        self.assertIn("index.md  markdown", out)


if __name__ == "__main__":
    unittest.main()

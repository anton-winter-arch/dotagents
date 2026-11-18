"""The file inventory and `tree`: every file the walk sees, by folder and
language, including the ones no parser reads. Expected counts come from
the tree built below."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_symbol_edges import run  # noqa: E402

import code_kg  # noqa: E402

TREE = {
    "a.py": "print(1)\n",
    "src/b.py": "def b():\n    return 1\n",
    "src/c.ts": "export function c() { return 1 }\n",
    "src/sub/d.sh": "d() { :; }\n",
    "bin/tool": "#!/bin/bash\ntool() { :; }\n",
    "bin/run": "#!/usr/bin/env -S python3 -u\ndef run():\n    pass\n",
    "bin/data": "no interpreter line here\n",
    "img/logo.png": "\x89PNG\r\n",
    "docs/x.md": "# X\n",
    "scripts/setup.fish": "set -x PATH $PATH /opt/bin\n",
    "scripts/win.bat": "@echo off\r\n",
    "scripts/legacy.ksh": "legacy() { :; }\n",
    ".env": "TOKEN=never-read\n",
    "package-lock.json": "{}\n",
    "node_modules/x.js": "skipped\n",
}


class InventoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-inv-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        for rel, text in TREE.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def json(self, *argv):
        rc, out, err = run(argv[0], str(self.repo), *argv[1:], "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def table(self, sql):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute(sql))
        con.close()
        return got


class TestLanguages(InventoryCase):
    def test_shebang_and_shell_dialects(self):
        got = dict(self.table("SELECT id, language FROM files"))
        self.assertEqual(got["bin/tool"], "bash")
        self.assertEqual(got["bin/run"], "python")
        self.assertEqual(got["scripts/legacy.ksh"], "bash")
        self.assertEqual(got["scripts/setup.fish"], "fish")
        self.assertEqual(got["scripts/win.bat"], "batch")
        self.assertNotIn("bin/data", got)

    def test_a_shebang_script_is_parsed(self):
        got = self.table("SELECT id FROM symbols")
        self.assertIn(("bin/tool::tool",), got)
        self.assertIn(("bin/run::run",), got)

    def test_files_no_parser_reads_are_inventoried(self):
        self.assertEqual(self.table(
            "SELECT path, ext, reason FROM other_files"), [
            (".env", "", "secret-name"),
            ("bin/data", "", "no-parser"),
            ("img/logo.png", ".png", "no-parser"),
            ("package-lock.json", ".json", "policy")])

    def test_unindexed_files_are_never_searchable(self):
        rc, out, _ = run("query", str(self.repo), "never", "--json")
        self.assertNotIn(".env", out)


class TestSecretNames(unittest.TestCase):
    def test_secret_named_files_are_never_read(self):
        for name in ("terraform.tfvars.json", "prod.auto.tfvars.json",
                     ".envrc", ".netrc", ".npmrc", ".pypirc", ".pgpass",
                     ".git-credentials", "id_ed25519", "credentials",
                     ".env.local", "secrets.yaml", "x.tfvars", "prod.env",
                     "web.config", "server.key", "cert.pem", "store.p12",
                     ".htpasswd", "service-account-prod.json"):
            self.assertEqual(code_kg.other_reason(name), "secret-name", name)
            self.assertIsNone(code_kg.language_of(name), name)
        self.assertEqual(code_kg.language_of("tsconfig.json"), "json")


# Every value below carries the marker; none may reach the graph, in any
# table, index or sidecar, while every name and the file it came from does.
MARK = "VALUE-MUST-NOT-LEAK"
ENV_FILES = {
    ".env": f"SECRET_TOKEN={MARK}-1\n"
            f"export DB_URL=\"{MARK}-2 quoted\"\n"
            f"# COMMENTED={MARK}-3\n"
            f"  SPACED = {MARK}-4\n"
            f"MULTI=\"{MARK}-5\n{MARK}-6\"\n"
            # Continuation lines shaped like NAME= are value, never names.
            f"PEM=\"{MARK}-10\nTAILNAME==\ninner_name=1\n\"\n",
    ".env.local": f"LOCAL_ONLY={MARK}-7\n",
    ".envrc": f"export DIRENV_KEY={MARK}-8\n",
    "config/prod.env": f"PROD_KEY={MARK}-9\n",
    "app.py": "import os\nTOKEN = os.environ.get('SECRET_TOKEN')\n",
}


class TestEnvFiles(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="ckg-env-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        for rel, text in ENV_FILES.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        for argv in (("ingest", "--keep-previous"), ("ingest",
                     "--keep-previous"), ("data",), ("search", MARK),
                     ("query", MARK), ("tree",)):
            rc, out, err = run(argv[0], str(self.repo), *argv[1:])
            self.assertNotIn(MARK, out + err, argv)

    def test_no_value_reaches_any_graph_file(self):
        stored = list(code_kg.kg_dir(self.repo).iterdir())
        self.assertTrue(stored)
        for f in stored:
            self.assertNotIn(MARK.encode(), f.read_bytes(), f.name)

    def test_names_are_known_with_the_file_they_come_from(self):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = set(con.execute(
            "SELECT src_file, node FROM data_edges WHERE node_kind='env'"
            " AND kind='write'"))
        con.close()
        self.assertLessEqual({
            (".env", "SECRET_TOKEN"), (".env", "DB_URL"), (".env", "SPACED"),
            (".env", "MULTI"), (".env.local", "LOCAL_ONLY"),
            (".envrc", "DIRENV_KEY"), ("config/prod.env", "PROD_KEY")}, got)
        self.assertNotIn((".env", "COMMENTED"), got)
        self.assertIn((".env", "PEM"), got)
        self.assertFalse({n for _, n in got} & {"TAILNAME", "inner_name"})


class TestTree(InventoryCase):
    def test_folders_tally_every_file(self):
        got = self.json("tree", "--limit", "0")
        rows = {f["path"]: f for f in got["folders"]}
        self.assertEqual(sorted(rows), ["", "bin", "docs", "img", "scripts",
                                        "src", "src/sub"])
        root = rows[""]
        self.assertEqual((root["files"], root["total"]), (3, 14))
        self.assertEqual(root["languages"], {
            "bash": 3, "batch": 1, "fish": 1, "markdown": 1, "python": 3,
            "typescript": 1})
        self.assertEqual(root["other"], {"(none)": 2, ".json": 1,
                                         ".png": 1})
        self.assertEqual((rows["src"]["files"], rows["src"]["total"]),
                         (2, 3))
        self.assertEqual(rows["bin"]["languages"], {"bash": 1, "python": 1})
        self.assertEqual(rows["bin"]["other"], {"(none)": 1})
        self.assertEqual(got["root"], str(self.repo))
        self.assertEqual(got["status"], "COMPLETE")

    def test_a_subfolder_and_depth(self):
        got = self.json("tree", "src", "--depth", "1")
        self.assertEqual([f["path"] for f in got["folders"]], ["src"])
        got = self.json("tree", "src")
        self.assertEqual([f["path"] for f in got["folders"]],
                         ["src", "src/sub"])

    def test_files_with_absolute_paths(self):
        got = self.json("tree", "bin", "--files", "--absolute")
        files = {f["path"]: f for f in got["files"]}
        self.assertEqual(sorted(files), ["bin/data", "bin/run", "bin/tool"])
        self.assertEqual(files["bin/run"]["language"], "python")
        self.assertIsNone(files["bin/data"]["language"])
        self.assertEqual(files["bin/data"]["reason"], "no-parser")
        self.assertEqual(files["bin/tool"]["absolute"],
                         str(self.repo / "bin" / "tool"))
        self.assertTrue(os.path.isabs(files["bin/tool"]["absolute"]))

    def test_the_cut_is_declared(self):
        got = self.json("tree", "--limit", "2")
        self.assertEqual(len(got["folders"]), 2)
        self.assertEqual(got["status"], "TRUNCATED 2 of 7")

    def test_text_render(self):
        rc, out, err = run("tree", str(self.repo), "--files")
        self.assertEqual(rc, 0, err)
        self.assertIn(str(self.repo), out)
        self.assertIn("src/sub/", out)
        self.assertIn("bin/data  (no-parser)", out)

    def test_a_new_file_of_any_kind_is_drift(self):
        (self.repo / "img" / "icon.svg").write_text("<svg/>",
                                                    encoding="utf-8")
        got = self.json("tree", "img")
        self.assertEqual(got["folders"][0]["other"], {".png": 1, ".svg": 1})


SHARED = ("glob_match", "tree_payload", "render_tree", "write_checkpoint",
          "_ro_connect", "classify_units", "est_tokens", "rank_from",
          "linked_store", "seed_gitignore")


class TestSharedBodies(unittest.TestCase):
    """Functions both engines carry with the same body, docstrings aside:
    a fix to one copy must reach the other."""

    def test_the_two_engines_agree(self):
        import ast
        if not code_kg.SIBLING_CLI.is_file():
            self.skipTest("markdown-kg is not installed beside code-kg")

        def bodies(path: Path) -> dict:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            out = {}
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and node.name in SHARED:
                    body = node.body
                    if body and isinstance(body[0], ast.Expr) and isinstance(
                            getattr(body[0], "value", None), ast.Constant):
                        body = body[1:]
                    out[node.name] = ast.dump(ast.Module(body=body,
                                                         type_ignores=[]))
            return out
        mine = bodies(Path(code_kg.__file__))
        theirs = bodies(code_kg.SIBLING_CLI)
        self.assertEqual(sorted(mine), sorted(SHARED))
        for name in mine:
            self.assertEqual(mine[name], theirs.get(name), name)


if __name__ == "__main__":
    unittest.main()

"""Scaffolder: seeds 19 files, never overwrites, is byte-identical across runs, and seeds the graph."""
from __future__ import annotations

import filecmp
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
SCAFFOLD = SKILL / "scripts" / "vault_scaffold.py"
TEMPLATE = SKILL / "templates" / "PROJECTS"
PROFILES = SKILL / "templates" / "markdown-kg-profiles.md"
KG = SKILL.parent / "markdown-kg" / "scripts" / "markdown_kg.py"
SEED_COUNT = 19


def run(*args: str, graph: bool = False) -> subprocess.CompletedProcess:
    extra = [] if graph else ["--no-graph"]
    return subprocess.run([sys.executable, str(SCAFFOLD), *args, *extra], capture_output=True, text=True)


def config_rows(vault: Path) -> dict:
    text = (vault / "markdown-kg" / "markdown-kg-config.md").read_text()
    return json.loads(re.search(r"```json\n(.*?)```", text, re.S).group(1))


def test_seed_writes_every_template_file(tmp_path: Path) -> None:
    result = run("--target", str(tmp_path), "--name", "TEST")
    assert result.returncode == 0, result.stderr
    dest = tmp_path / "PROJECTS" / "TEST"
    names = sorted(p.name for p in dest.iterdir())
    assert names == sorted(p.name for p in TEMPLATE.iterdir())
    assert len(names) == SEED_COUNT
    match, mismatch, errors = filecmp.cmpfiles(TEMPLATE, dest, names, shallow=False)
    assert not mismatch and not errors


def test_rerun_skips_everything_and_writes_nothing(tmp_path: Path) -> None:
    run("--target", str(tmp_path), "--name", "TEST")
    dest = tmp_path / "PROJECTS" / "TEST"
    (dest / "00-brd.md").write_text("edited by hand\n")
    before = {p.name: p.stat().st_mtime_ns for p in dest.iterdir()}
    result = run("--target", str(tmp_path), "--name", "TEST")
    assert result.returncode == 0
    assert result.stdout.count("skipped") == SEED_COUNT + 1  # summary line plus one per file
    assert (dest / "00-brd.md").read_text() == "edited by hand\n"
    assert {p.name: p.stat().st_mtime_ns for p in dest.iterdir()} == before


def test_partial_vault_gets_only_the_gaps(tmp_path: Path) -> None:
    dest = tmp_path / "PROJECTS" / "TEST"
    dest.mkdir(parents=True)
    (dest / "index.md").write_text("mine\n")
    result = run("--target", str(tmp_path), "--name", "TEST")
    assert result.returncode == 0
    assert (dest / "index.md").read_text() == "mine\n"
    assert len(list(dest.iterdir())) == SEED_COUNT


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    result = run("--target", str(tmp_path), "--name", "TEST", "--dry-run")
    assert result.returncode == 0
    assert not (tmp_path / "PROJECTS").exists()
    assert result.stdout.count("would write") == SEED_COUNT + 1


def test_two_seeds_are_byte_identical(tmp_path: Path) -> None:
    run("--target", str(tmp_path / "a"), "--name", "X")
    run("--target", str(tmp_path / "b"), "--name", "X")
    cmp = filecmp.dircmp(tmp_path / "a" / "PROJECTS" / "X", tmp_path / "b" / "PROJECTS" / "X")
    assert not cmp.diff_files and not cmp.left_only and not cmp.right_only


def test_name_must_be_a_single_visible_folder(tmp_path: Path) -> None:
    for bad in ("a/b", ".hidden", "..", "tab\there"):
        assert run("--target", str(tmp_path), "--name", bad).returncode == 2, bad


def test_symlinked_file_is_refused_not_followed(tmp_path: Path) -> None:
    dest = tmp_path / "PROJECTS" / "T"
    dest.mkdir(parents=True)
    outside = tmp_path / "OUTSIDE.md"
    (dest / "log.md").symlink_to(outside)
    result = run("--target", str(tmp_path), "--name", "T")
    assert result.returncode == 1
    assert not outside.exists()
    assert "log.md" in result.stdout and "symlink" in result.stdout
    assert len([p for p in dest.iterdir() if not p.is_symlink()]) == SEED_COUNT - 1


def test_symlinked_projects_dir_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "PROJECTS").symlink_to(elsewhere)
    result = run("--target", str(tmp_path / "v"), "--name", "T")
    assert result.returncode == 1
    assert not any(elsewhere.iterdir())


@pytest.mark.skipif(not KG.exists(), reason="markdown-kg not installed beside this skill")
def test_symlinked_graph_dir_is_refused(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    vault = tmp_path / "v" / "PROJECTS" / "T"
    vault.mkdir(parents=True)
    (vault / "markdown-kg").symlink_to(elsewhere)
    result = run("--target", str(tmp_path / "v"), "--name", "T", graph=True)
    assert result.returncode == 1
    assert "symlink" in result.stdout
    assert not any(elsewhere.iterdir())


@pytest.mark.skipif(not KG.exists(), reason="markdown-kg not installed beside this skill")
def test_symlinked_file_in_graph_dir_is_refused(tmp_path: Path) -> None:
    assert run("--target", str(tmp_path / "a"), "--name", "A", graph=True).returncode == 0
    other_db = tmp_path / "a" / "PROJECTS" / "A" / "markdown-kg" / "markdown-kg.db"
    before = other_db.read_bytes()
    kg_dir = tmp_path / "b" / "PROJECTS" / "B" / "markdown-kg"
    kg_dir.mkdir(parents=True)
    (kg_dir / "markdown-kg.db").symlink_to(other_db)
    result = run("--target", str(tmp_path / "b"), "--name", "B", graph=True)
    assert result.returncode == 1
    assert "symlink" in result.stdout
    assert other_db.read_bytes() == before


@pytest.mark.skipif(not KG.exists(), reason="markdown-kg not installed beside this skill")
def test_seed_initializes_configures_and_ingests_the_graph(tmp_path: Path) -> None:
    result = run("--target", str(tmp_path), "--name", "T", graph=True)
    assert result.returncode == 0, result.stdout + result.stderr
    vault = tmp_path / "PROJECTS" / "T"
    shipped = json.loads(re.search(r"```json\n(.*?)```", PROFILES.read_text(), re.S).group(1))
    rows = config_rows(vault)
    for key in ("ignore", "profiles"):
        assert {r["path"] for r in shipped[key]} <= {r["path"] for r in rows[key]}, key
    found = subprocess.run([sys.executable, str(KG), "search", str(vault), "learning sweep", "--json"],
                           capture_output=True, text=True)
    assert found.returncode == 0, found.stderr
    ids = [h["section_id"] for h in json.loads(found.stdout)["results"]]
    assert ids and not any(i.startswith(("AGENTS", "CLAUDE")) for i in ids), ids


@pytest.mark.skipif(not KG.exists(), reason="markdown-kg not installed beside this skill")
def test_rerun_restores_only_missing_rows_and_keeps_the_operators(tmp_path: Path) -> None:
    run("--target", str(tmp_path), "--name", "T", graph=True)
    vault = tmp_path / "PROJECTS" / "T"
    config = vault / "markdown-kg" / "markdown-kg-config.md"
    rows = config_rows(vault)
    rows["profiles"] = [r for r in rows["profiles"] if r["path"] != "index.md"]
    rows["profiles"].append({"path": "notes-learnings.md", "profile": "reference"})
    text = config.read_text()
    block = re.search(r"```json\n(.*?)```", text, re.S)
    config.write_text(text[:block.start(1)] + json.dumps(rows, indent=2) + "\n" + text[block.end(1):])
    result = run("--target", str(tmp_path), "--name", "T", graph=True)
    assert result.returncode == 0 and "1 profile row(s) merged" in result.stdout, result.stdout
    paths = [r["path"] for r in config_rows(vault)["profiles"]]
    assert paths.count("index.md") == 1 and "notes-learnings.md" in paths
    again = run("--target", str(tmp_path), "--name", "T", graph=True)
    assert again.returncode == 0 and "nothing to ingest" in again.stdout, again.stdout

"""Compatibility with the skills that read or write a project vault.

sprint-board owns user-stories.md; markdown-kg reads the vault as a graph root. Each test
is the whole coupling to that skill: a divergence fails here rather than months later.
The reference-vault check runs only when PKV_REFERENCE_VAULTS lists the machine's working
vaults, because naming them here would name a project.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
SKILLS = SKILL.parent
SCAFFOLD = SKILL / "scripts" / "vault_scaffold.py"
LINT = SKILL / "scripts" / "vault_lint.py"
BOARD_SCAFFOLD = SKILLS / "sprint-board" / "scripts" / "board_scaffold.py"
BOARD_LINT = SKILLS / "sprint-board" / "scripts" / "board_lint.py"
KG = SKILLS / "markdown-kg" / "scripts" / "markdown_kg.py"
PROFILES = SKILL / "templates" / "markdown-kg-profiles.md"


def seed(tmp_path: Path, graph: bool = False) -> Path:
    extra = [] if graph else ["--no-graph"]
    subprocess.run([sys.executable, str(SCAFFOLD), "--target", str(tmp_path), "--name", "T", *extra], check=True, capture_output=True)
    return tmp_path / "PROJECTS" / "T"


def run(*args: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=cwd)


@pytest.mark.skipif(not BOARD_LINT.exists(), reason="sprint-board not installed beside this skill")
def test_sprint_board_scaffold_appended_to_the_seed_lints_clean(tmp_path: Path) -> None:
    v = seed(tmp_path)
    spine = tmp_path / "spine.json"
    spine.write_text(json.dumps({"epics": [{"title": "Ship the widget", "features": [
        {"title": "Assemble the widget", "stories": [{"title": "Cut the parts"}]}]}]}))
    board = run(BOARD_SCAFFOLD, spine)
    assert board.returncode == 0, board.stderr
    p = v / "user-stories.md"
    p.write_text(p.read_text() + "\n---\n\n" + board.stdout)
    # A fresh scaffold carries template bodies the author still has to write, which
    # board_lint reports as residue by design. The vault's responsibility is the
    # structure, so no structural finding may appear.
    result = run(BOARD_LINT, p, "--json")
    codes = {f["code"] for f in json.loads(result.stdout)["findings"]}
    structural = {"no-items", "heading-level", "bad-id-form", "missing-block", "bad-parent", "unknown-parent"}
    assert not (codes & structural), codes
    # the appended board must not trip the vault linter either
    assert run(LINT, v).returncode == 0


@pytest.mark.skipif(not KG.exists(), reason="markdown-kg not installed beside this skill")
def test_markdown_kg_ingest_resolves_edges_dates_and_supersession(tmp_path: Path) -> None:
    # the scaffolder initializes the graph and merges the shipped profile rows
    v = seed(tmp_path, graph=True)
    (v / "notes-meeting-notes.md").write_text(
        "---\ntype: meeting_note\ntitle: notes-meeting-notes\ncoverage_start: 2026-01-01\n---\n\n# MEETING-NOTES\n"
        "[2026-FEBRUARY](#2026-FEBRUARY)\n[2026-JANUARY](#2026-JANUARY)\n\n---\n# 2026-FEBRUARY\n\n"
        "## 2026-02-01-STANDUP\n\nThe deploy target moved to the blue cluster after the outage review.\n\n"
        "### DECISIONS\n\n- 2026-02-01 - deploy target is the blue cluster - supersedes 2026-01-01 kickoff, capacity\n\n"
        "---\n# 2026-JANUARY\n\n"
        "## 2026-01-01-KICKOFF\n\nThe deploy target is the green cluster for the first release.\n\n"
        "**SUPERSEDED**: 2026-02-01 [[notes-meeting-notes#2026-02-01-STANDUP]]\n\n"
        "### DECISIONS\n\n- 2026-01-01 - deploy target is the green cluster - first release\n")
    (v / "notes-learnings.md").write_text(
        "---\ntype: reference\ntitle: notes-learnings\ncoverage_start: 2026-02-01\n---\n\n# LEARNINGS\n\n"
        "# 2026-FEBRUARY\n\n## 2026-02-01 - the deploy target moved to blue\n\n"
        "### The deploy target is the blue cluster\n\nSettled at [[notes-meeting-notes#2026-02-01-STANDUP]] after the outage review.\n")
    lint = run(LINT, v)
    assert lint.returncode == 0, lint.stdout

    ingest = run(KG, "ingest", v)
    assert ingest.returncode == 0, ingest.stderr + ingest.stdout
    m = re.search(r"edges: (\d+) resolved, (\d+) unresolved, (\d+) ambiguous", ingest.stdout)
    assert m and int(m.group(1)) > 0 and m.group(2) == "0" and m.group(3) == "0", ingest.stdout

    unresolved = run(KG, "links", v, "--unresolved")
    assert "no outbound links" in unresolved.stdout or unresolved.stdout.strip() == "", unresolved.stdout

    # month H1s group the entries; each dated H2 stays its own unit with its own date
    sections = run(KG, "sections", v, "notes-meeting-notes", "--json")
    assert sections.returncode == 0, sections.stderr
    rows = json.loads(sections.stdout)
    kickoff = next((r for r in rows if r["heading_path"].endswith("KICKOFF")), None)
    standup = next((r for r in rows if r["heading_path"].endswith("STANDUP")), None)
    assert kickoff and standup, sections.stdout
    assert kickoff["is_unit"] and standup["is_unit"], (kickoff, standup)
    assert kickoff["slot"] == "superseded", kickoff
    assert standup["doc_date"].startswith("2026-02-01"), standup

    search = run(KG, "search", v, "deploy target cluster", "--json")
    assert search.returncode == 0, search.stderr
    ids = [h["section_id"] for h in json.loads(search.stdout)["results"]]
    first_meeting = next((i for i in ids if i.startswith("notes-meeting-notes#")), "")
    assert "STANDUP" in first_meeting, ids


REFERENCE_VAULTS = [Path(p).expanduser() for p in os.environ.get("PKV_REFERENCE_VAULTS", "").split(os.pathsep) if p]
STRUCTURAL = {"flat", "filename", "family", "unreadable"}  # what the template's grammar decides, not what a note says


@pytest.mark.skipif(not REFERENCE_VAULTS, reason="PKV_REFERENCE_VAULTS not set")
@pytest.mark.parametrize("vault", REFERENCE_VAULTS, ids=lambda p: p.name)
def test_reference_vault_matches_the_template_structurally(vault: Path) -> None:
    # The machine's working vaults, listed outside the repo, are the compatibility bar: a
    # template change that makes one of them structurally non-conforming fails here.
    # Content findings (a dangling link, a pasted heading) are the vault's own worklist.
    assert vault.is_dir(), f"reference vault missing: {vault}"
    result = run(LINT, vault, "--json")
    structural = [f for f in json.loads(result.stdout) if f["check"] in STRUCTURAL]
    assert not structural, json.dumps(structural, indent=2)

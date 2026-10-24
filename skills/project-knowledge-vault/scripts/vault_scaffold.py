#!/usr/bin/env python3
"""Seed a project knowledge vault from the shipped template.

    vault_scaffold.py --target <path> --name <NAME> [--dry-run] [--no-graph]

Copies every file in templates/PROJECTS/ to <target>/PROJECTS/<NAME>/. A file that
already exists is skipped and reported, so a run against a partly built vault fills the
gaps and touches nothing else. Placeholders stay as placeholders: no date is resolved,
so two runs on different days produce byte-identical notes.

Then seeds the vault's knowledge graph, because that is how a grown vault is read: runs
markdown-kg's `init` when the vault has no graph config, merges the rows in
templates/markdown-kg-profiles.md that the config lacks, and ingests when a note or a
row was added. markdown-kg is found beside this skill; when it is absent the step is
reported and skipped. `--no-graph` skips it.

Standard library only, offline. Exit 0 when every file was written or deliberately
skipped, 1 when any file could be neither or the graph step failed, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "templates" / "PROJECTS"
PROFILES = SKILL_DIR / "templates" / "markdown-kg-profiles.md"
KG = SKILL_DIR.parent / "markdown-kg" / "scripts" / "markdown_kg.py"
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.S)


def template_files() -> list[Path]:
    """Every seed file, in a stable order."""
    return sorted(p for p in TEMPLATE_DIR.iterdir() if p.is_file())


def scaffold(target: Path, name: str, dry_run: bool = False) -> tuple[list[str], list[str], list[str]]:
    """Copy the seed into target/PROJECTS/name. Returns (written, skipped, failed)."""
    dest = target / "PROJECTS" / name
    written: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    # A symlink anywhere on the destination path could carry the seed outside the vault.
    for part in (target / "PROJECTS", dest):
        if part.is_symlink():
            return written, skipped, [f"{part}: is a symlink; refusing to seed through it"]
    for src in template_files():
        out = dest / src.name
        if out.is_symlink():
            failed.append(f"{src.name}: destination is a symlink; refusing to write through it")
            continue
        if out.exists():
            skipped.append(src.name)
            continue
        if dry_run:
            written.append(src.name)
            continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            # O_EXCL and O_NOFOLLOW: create only, never through a link planted between the check and the write
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
            with os.fdopen(fd, "wb") as fh:
                fh.write(src.read_bytes())
            written.append(src.name)
        except OSError as exc:
            failed.append(f"{src.name}: {exc}")
    return written, skipped, failed


def kg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KG), *args], capture_output=True, text=True)


def merge_profiles(config: Path) -> int:
    """Add the shipped ignore and profile rows whose path the config lacks. Returns rows added."""
    if config.is_symlink():
        raise OSError(f"{config} is a symlink; refusing to write through it")
    text = config.read_text(encoding="utf-8")
    block = JSON_BLOCK.search(text)
    shipped = JSON_BLOCK.search(PROFILES.read_text(encoding="utf-8"))
    if not block or not shipped:
        raise ValueError(f"no json block in {config if not block else PROFILES}")
    data = json.loads(block.group(1))
    added = 0
    for key, rows in json.loads(shipped.group(1)).items():
        have = {row.get("path") for row in data.setdefault(key, [])}
        for row in rows:
            if row["path"] not in have:
                data[key].append(row)
                added += 1
    if added:
        body = json.dumps(data, indent=2) + "\n"
        config.write_text(text[:block.start(1)] + body + text[block.end(1):], encoding="utf-8")
    return added


def seed_graph(vault: Path, notes_written: int) -> tuple[bool, str]:
    """Initialize, configure and ingest the vault's graph. Returns (ok, report line)."""
    if not KG.is_file():
        return True, "graph: skipped, markdown-kg is not installed beside this skill; run its init and merge templates/markdown-kg-profiles.md by hand"
    kg_dir = vault / "markdown-kg"
    if kg_dir.is_symlink() or (kg_dir.is_dir() and any(p.is_symlink() for p in kg_dir.iterdir())):
        return False, f"graph: {kg_dir} is or contains a symlink; refusing to write through it"
    config = kg_dir / "markdown-kg-config.md"
    initialized = False
    if not config.exists():
        r = kg("init", str(vault))
        if r.returncode != 0:
            return False, f"graph: init failed: {(r.stderr or r.stdout).strip()}"
        initialized = True
    try:
        added = merge_profiles(config)
    except (OSError, ValueError) as exc:
        return False, f"graph: could not merge profile rows: {exc}"
    if not (initialized or added or notes_written):
        return True, "graph: config already has every profile row, nothing to ingest"
    r = kg("ingest", str(vault))
    if r.returncode != 0:
        return False, f"graph: ingest failed: {(r.stderr or r.stdout).strip()}"
    verb = "initialized" if initialized else "updated"
    return True, f"graph: {verb} markdown-kg/, {added} profile row(s) merged, ingested; gitignore markdown-kg/*.db*"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, type=Path, help="folder that holds (or will hold) PROJECTS/")
    parser.add_argument("--name", required=True, help="the project vault's folder name under PROJECTS/")
    parser.add_argument("--dry-run", action="store_true", help="print the file list and write nothing")
    parser.add_argument("--no-graph", action="store_true", help="seed the notes only, without the markdown-kg graph")
    args = parser.parse_args(argv)

    bad = {os.sep, os.altsep or os.sep}
    if any(c in args.name for c in bad) or args.name in ("", ".", "..") or args.name.startswith(".") or not args.name.isprintable():
        parser.error("--name is a single, visible folder name")
    if not TEMPLATE_DIR.is_dir():
        parser.error(f"template folder missing: {TEMPLATE_DIR}")

    written, skipped, failed = scaffold(args.target, args.name, args.dry_run)
    verb = "would write" if args.dry_run else "wrote"
    dest = args.target / "PROJECTS" / args.name
    print(f"{dest}: {verb} {len(written)}, skipped {len(skipped)}, failed {len(failed)}")
    for f in written:
        print(f"  {verb:<11} {f}")
    for f in skipped:
        print(f"  skipped     {f} (exists)")
    for f in failed:
        print(f"  FAILED      {f}")
    if failed:
        return 1
    if args.no_graph:
        return 0
    if args.dry_run:
        print("graph: would initialize markdown-kg/ and merge the profile rows")
        return 0
    ok, report = seed_graph(dest, len(written))
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

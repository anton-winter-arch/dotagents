#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""obsidian_kg.py - turn any Obsidian vault into a queryable SQLite knowledge graph.

Stdlib only, Python 3.10+. Storage is `<vault>/.obsidian-kg.db` (SQLite + FTS5).
The vault directory is always a CLI argument: nothing here is tied to any
particular vault, machine, or agent, and nothing here ever sends vault text
anywhere - the whole engine is offline.

Design goals (sibling of okf-kg's okf_kg.py, adapted to Obsidian syntax):
  * deterministic - `ingest` is a pure parse of the vault: same vault bytes
                    produce the same db content (the single `meta.ingested_at`
                    timestamp is the only exception). Every ingest is an
                    idempotent full rebuild in sorted file order.
  * faithful      - links are extracted fence-aware (fenced code blocks and
                    inline code never become edges) and wikilinks resolve the
                    way Obsidian resolves them: vault-wide case-insensitive
                    basename match, honoring frontmatter `aliases:`; a
                    path-qualified link disambiguates by path suffix; a bare
                    link whose basename collides is recorded AMBIGUOUS (edge
                    to none) - never guessed silently.

Commands:
  ingest <vault>                       full rebuild: notes, props, tags, edges
  query <vault> <fts-query> [--limit N]  BM25-ranked FTS5 search
  note <vault> <name-or-path>          full note + frontmatter
  backlinks <vault> <note>             inbound edges (syntax + kind)
  links <vault> <note>                 outbound edges (incl. unresolved)
  neighbors <vault> <note> [--depth N] BFS over resolved edges (default 1)
  path <vault> <a> <b>                 shortest path over resolved edges
  tags <vault> [tag]                   tag counts, or notes bearing a tag
  stats <vault>                        counts, orphans, unresolved/ambiguous
"""
from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB_NAME = ".obsidian-kg.db"

# Folders Obsidian hides or that are never vault notes; any dot folder/file is
# excluded too (mirrors index_vault.py in the obsidian skill).
SKIP_FOLDERS = {".git", ".obsidian", ".trash", ".smart-env", "node_modules",
                ".venv", "venv", "__pycache__", ".pytest_cache"}

# Wikilink targets pointing at binary/asset embeds - never note edges.
ASSET_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "pdf",
              "mp3", "wav", "m4a", "ogg", "flac", "mp4", "mov", "mkv", "webm",
              "zip", "csv", "json", "canvas", "excalidraw"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes(
  id           TEXT PRIMARY KEY,      -- vault-relative path without .md
  path         TEXT NOT NULL UNIQUE,  -- vault-relative path with .md
  title        TEXT NOT NULL DEFAULT '',
  tags         TEXT NOT NULL DEFAULT '',  -- comma-joined (FTS convenience)
  aliases      TEXT NOT NULL DEFAULT '',  -- comma-joined (FTS convenience)
  content_hash TEXT NOT NULL,             -- sha256 of raw file text
  body         TEXT NOT NULL              -- raw file text
);
CREATE TABLE IF NOT EXISTS properties(   -- scalar frontmatter key/values
  note_id TEXT NOT NULL,
  key     TEXT NOT NULL,
  value   TEXT NOT NULL,
  PRIMARY KEY (note_id, key)
);
CREATE TABLE IF NOT EXISTS tags(
  note_id TEXT NOT NULL,
  tag     TEXT NOT NULL,
  PRIMARY KEY (note_id, tag)
);
CREATE TABLE IF NOT EXISTS aliases(
  note_id TEXT NOT NULL,
  alias   TEXT NOT NULL,
  PRIMARY KEY (note_id, alias)
);
CREATE TABLE IF NOT EXISTS edges(
  src    TEXT NOT NULL,               -- note id
  dst    TEXT,                        -- note id; NULL if unresolved/ambiguous
  target TEXT NOT NULL,               -- target as written (no heading/alias)
  syntax TEXT NOT NULL,               -- 'wiki' | 'md'
  kind   TEXT NOT NULL,               -- 'link' | 'embed'
  status TEXT NOT NULL,               -- 'resolved' | 'unresolved' | 'ambiguous'
  PRIMARY KEY (src, syntax, kind, target)
);
CREATE TABLE IF NOT EXISTS meta(       -- the only non-deterministic content
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  id UNINDEXED, title, tags, aliases, body,
  content='notes', content_rowid='rowid');
"""

WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]]+)\]\]")
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^()]+)\)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vault_dir(arg: str) -> Path:
    vault = Path(arg).expanduser().resolve()
    if not vault.is_dir():
        sys.exit(f"error: vault directory not found: {arg}")
    return vault


def connect(vault: Path, must_exist: bool = False) -> sqlite3.Connection:
    db = vault / DB_NAME
    if must_exist and not db.exists():
        sys.exit(f"error: no database at {db} - run `ingest` on this vault first")
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    return con


# ---------- parsing (deterministic, stdlib) ----------
def parse_frontmatter(text: str) -> tuple[dict, int]:
    """Parse the YAML subset Obsidian Properties use: scalar `key: value`
    (optionally quoted), inline lists `[a, b]`, and block lists. Returns
    (meta, body_start). Files without valid frontmatter get ({}, 0)."""
    if not text.startswith("---\n"):
        return {}, 0
    end = text.find("\n---\n", 3)
    if end < 0:
        return {}, 0
    meta: dict = {}
    key = None
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"\s+-\s+(.*)$", line)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(_unquote(item.group(1)))
            continue
        m = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw.startswith("[") and raw.endswith("]"):
            meta[key] = [_unquote(v.strip()) for v in raw[1:-1].split(",") if v.strip()]
        elif raw == "":
            meta[key] = []  # block list may follow
        else:
            meta[key] = _unquote(raw)
    return meta, end + 5


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _listify(v) -> list[str]:
    """Frontmatter tags/aliases may be a list or a comma-joined scalar."""
    if isinstance(v, list):
        return [str(x).strip().lstrip("#") for x in v if str(x).strip()]
    return [t.strip().lstrip("#") for t in str(v).split(",") if t.strip()]


def strip_code(text: str) -> str:
    """Blank out fenced code blocks (``` / ~~~) and inline code spans, keeping
    line structure, so link extraction never sees code."""
    out, in_fence, marker = [], False, ""
    for line in text.splitlines():
        s = line.lstrip()
        if in_fence:
            if s.startswith(marker):
                in_fence, marker = False, ""
            out.append("")
            continue
        if s.startswith("```") or s.startswith("~~~"):
            in_fence, marker = True, s[:3]
            out.append("")
            continue
        out.append(INLINE_CODE_RE.sub("", line))
    return "\n".join(out)


def extract_wikilinks(text: str) -> list[tuple[str, str]]:
    """Wikilink (target, kind) pairs in document order, from fence-stripped
    text. Target keeps its path fragment but drops `#heading`/`#^block` and
    `|alias` parts. kind is 'embed' for `![[...]]`, else 'link'."""
    out = []
    for m in WIKILINK_RE.finditer(strip_code(text)):
        inner = m.group(2).split("|", 1)[0]
        target = inner.split("#", 1)[0].strip().rstrip("\\").strip()
        if not target:
            continue  # [[#heading]] self-references are not edges
        out.append((target, "embed" if m.group(1) else "link"))
    return out


def extract_md_links(text: str) -> list[str]:
    """Standard markdown link targets in document order, from fence-stripped
    text. Images (`![...]`), external schemes, and bare fragments skipped;
    `<...>` wrapping, `"title"` suffixes, and fragments stripped."""
    out = []
    for m in MD_LINK_RE.finditer(strip_code(text)):
        target = m.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1:target.index(">")]
        else:
            tm = re.match(r'^(.*?)\s+"[^"]*"$', target)  # trailing "title"
            if tm:
                target = tm.group(1)
        target = target.split("#", 1)[0].strip()
        if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            continue
        out.append(target)
    return out


def resolve_md_link(target: str, src_rel: str) -> str | None:
    """Resolve a markdown link target to a note id (vault-relative, no .md),
    or None if it is not a .md file inside the vault."""
    target = urllib.parse.unquote(target)
    if not target.lower().endswith(".md"):
        return None
    if target.startswith("/"):
        rel = posixpath.normpath(target.lstrip("/"))
    else:
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(src_rel), target))
    if rel.startswith(".."):
        return None
    return rel[: -len(".md")]


def resolve_wikilink(target: str, ids: list[str], by_base: dict[str, list[str]],
                     by_alias: dict[str, list[str]]) -> tuple[str | None, str]:
    """Resolve a wikilink target the way Obsidian does. Returns (dst, status):
      * path fragment present -> unique case-insensitive path-suffix match,
        multiple matches AMBIGUOUS, none unresolved
      * bare name -> case-insensitive basename match; unique wins, collision
        is AMBIGUOUS (never guessed); no basename hit falls through to
        frontmatter aliases (same unique/ambiguous rule)
    """
    t = target.strip().strip("/")
    if t.lower().endswith(".md"):
        t = t[: -len(".md")]
    tl = t.lower()
    if "/" in tl:
        cands = sorted(i for i in ids
                       if i.lower() == tl or i.lower().endswith("/" + tl))
    else:
        cands = sorted(by_base.get(tl, []))
        if not cands:
            cands = sorted(by_alias.get(tl, []))
    if len(cands) == 1:
        return cands[0], "resolved"
    if len(cands) > 1:
        return None, "ambiguous"
    return None, "unresolved"


# ---------- vault walking (git parity, dot folders excluded) ----------
def walk_vault(vault: Path) -> list[Path]:
    """All vault .md files, sorted for determinism. In a git repo, enumerate
    via `git ls-files --cached --others --exclude-standard` (exactly the set
    git does not ignore); otherwise a skip-folder os.walk. Dot folders/files
    and SKIP_FOLDERS are always excluded - Obsidian hides them."""
    files: list[Path] | None = None
    try:
        out = subprocess.run(
            ["git", "-C", str(vault), "ls-files", "-z",
             "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True)
        if out.returncode == 0:
            # -z: NUL-separated, unquoted - non-ASCII filenames survive
            # (default core.quotePath=true C-quotes them otherwise)
            files = [vault / ln for ln in out.stdout.split("\0")
                     if ln.endswith(".md")]
    except Exception:
        files = None
    # Git parity is right for a TRACKED vault -- but a vault can be deliberately
    # gitignored (client material, a generated build output), and then `git ls-files`
    # returns nothing, the ingest reports "0 notes", and it reads as success. Falling
    # back to the walk whenever git yields no notes but the tree has some makes the
    # empty case impossible to mistake for a clean one.
    if not files:
        files = None
    if files is None:
        files = []
        for root, dirs, names in os.walk(vault):
            dirs[:] = [d for d in dirs
                       if d not in SKIP_FOLDERS and not d.startswith(".")]
            files.extend(Path(root) / n for n in names if n.endswith(".md"))
    result = []
    for p in files:
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(vault)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(part in SKIP_FOLDERS for part in rel.parts):
            continue
        result.append(p)
    return sorted(set(result))


# ---------- ingest (idempotent full rebuild) ----------
def ingest(vault: Path) -> dict:
    con = connect(vault)
    report = {"notes": 0, "resolved": 0, "unresolved": 0, "ambiguous": 0,
              "skipped_assets": 0}

    parsed: dict[str, dict] = {}  # id -> {rel, text, meta}
    for f in walk_vault(vault):
        rel = f.relative_to(vault).as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, _ = parse_frontmatter(text)
        parsed[rel[: -len(".md")]] = {"rel": rel, "text": text, "meta": meta}

    ids = sorted(parsed)
    by_base: dict[str, list[str]] = {}
    by_alias: dict[str, list[str]] = {}
    for nid in ids:
        by_base.setdefault(nid.rsplit("/", 1)[-1].lower(), []).append(nid)
        for alias in _listify(parsed[nid]["meta"].get("aliases", [])):
            by_alias.setdefault(alias.lower(), []).append(nid)

    # full rebuild: wipe everything, re-insert in sorted order, rebuild FTS
    for table in ("notes", "properties", "tags", "aliases", "edges", "meta"):
        con.execute(f"DELETE FROM {table}")

    for nid in ids:
        doc = parsed[nid]
        meta, text = doc["meta"], doc["text"]
        h1 = H1_RE.search(text)
        title = str(meta.get("title")
                    or (h1.group(1) if h1 else nid.rsplit("/", 1)[-1]))
        tag_list = _listify(meta.get("tags", []))
        alias_list = _listify(meta.get("aliases", []))
        con.execute(
            "INSERT INTO notes(id, path, title, tags, aliases, content_hash, body)"
            " VALUES (?,?,?,?,?,?,?)",
            (nid, doc["rel"], title, ", ".join(tag_list), ", ".join(alias_list),
             hashlib.sha256(text.encode()).hexdigest(), text))
        report["notes"] += 1
        for tag in sorted(set(tag_list)):
            con.execute("INSERT INTO tags(note_id, tag) VALUES (?,?)", (nid, tag))
        for alias in sorted(set(alias_list)):
            con.execute("INSERT INTO aliases(note_id, alias) VALUES (?,?)",
                        (nid, alias))
        for key in sorted(meta):
            val = meta[key]
            if key in ("tags", "aliases"):
                continue  # normalized into their own tables
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            con.execute(
                "INSERT INTO properties(note_id, key, value) VALUES (?,?,?)",
                (nid, key, str(val)))

        # edges: wikilinks (fence-aware) then markdown links
        rows: list[tuple] = []
        for target, kind in extract_wikilinks(text):
            base = target.rsplit("/", 1)[-1]
            ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
            if ext in ASSET_EXTS:
                report["skipped_assets"] += 1
                continue
            dst, status = resolve_wikilink(target, ids, by_base, by_alias)
            rows.append((nid, dst, target, "wiki", kind, status))
        for target in extract_md_links(text):
            dst = resolve_md_link(target, doc["rel"])
            if dst is None:
                report["skipped_assets"] += 1
                continue
            status = "resolved" if dst in parsed else "unresolved"
            rows.append((nid, dst if status == "resolved" else None,
                         urllib.parse.unquote(target), "md", "link", status))
        for row in rows:
            cur = con.execute(
                "INSERT OR IGNORE INTO edges(src, dst, target, syntax, kind,"
                " status) VALUES (?,?,?,?,?,?)", row)
            if cur.rowcount:
                report[row[5]] += 1

    con.execute("INSERT INTO notes_fts(notes_fts) VALUES ('rebuild')")
    con.execute("INSERT INTO meta(key, value) VALUES ('ingested_at', ?)",
                (now_utc(),))
    con.commit()
    con.close()
    return report


def cmd_ingest(args: argparse.Namespace) -> int:
    r = ingest(vault_dir(args.vault))
    print(f"ingest: {r['notes']} notes; edges: {r['resolved']} resolved, "
          f"{r['unresolved']} unresolved, {r['ambiguous']} ambiguous; "
          f"{r['skipped_assets']} non-note targets skipped")
    return 0


# ---------- note name resolution (CLI arguments) ----------
def resolve_note_arg(con: sqlite3.Connection, name: str) -> str:
    """Resolve a CLI note argument to a note id: exact id/path, then
    case-insensitive path suffix or basename, then frontmatter alias.
    Exits with candidates listed when ambiguous, never guesses."""
    n = name.strip().strip("/")
    if n.lower().endswith(".md"):
        n = n[: -len(".md")]
    ids = [r[0] for r in con.execute("SELECT id FROM notes ORDER BY id")]
    if n in ids:
        return n
    nl = n.lower()
    cands = sorted(i for i in ids
                   if i.lower() == nl or i.lower().endswith("/" + nl))
    if not cands:
        cands = sorted(r[0] for r in con.execute(
            "SELECT note_id FROM aliases WHERE lower(alias) = ?", (nl,)))
    if len(cands) == 1:
        return cands[0]
    con.close()
    if cands:
        sys.exit(f"error: ambiguous note {name!r} - candidates: "
                 + ", ".join(cands))
    sys.exit(f"error: unknown note {name!r} (find notes with `query`)")


# ---------- query / traversal (read-only) ----------
def query(vault: Path, q: str, limit: int = 20) -> list[dict]:
    """FTS5 search over notes, best BM25 rank first."""
    con = connect(vault, must_exist=True)
    try:
        rows = con.execute(
            "SELECT n.id, n.path, n.title,"
            " snippet(notes_fts, 4, '[', ']', ' ... ', 12)"
            " FROM notes_fts JOIN notes n ON n.rowid = notes_fts.rowid"
            " WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?",
            (q, limit)).fetchall()
    except sqlite3.OperationalError as e:
        con.close()
        raise ValueError(f"invalid FTS5 query {q!r}: {e}") from e
    con.close()
    return [{"id": r[0], "path": r[1], "title": r[2], "snippet": r[3]}
            for r in rows]


def _adjacency(con: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """Undirected adjacency over resolved edges: id -> [(other, syntax/kind)]."""
    adj: dict[str, list[tuple[str, str]]] = {}
    for src, dst, syntax, kind in con.execute(
            "SELECT src, dst, syntax, kind FROM edges WHERE status='resolved'"):
        label = f"{syntax}/{kind}"
        adj.setdefault(src, []).append((dst, label))
        adj.setdefault(dst, []).append((src, label))
    return adj


def neighbors(vault: Path, name: str, depth: int = 1) -> list[dict]:
    """BFS out to `depth` hops over resolved edges (both directions)."""
    con = connect(vault, must_exist=True)
    nid = resolve_note_arg(con, name)
    adj = _adjacency(con)
    con.close()
    out, seen, frontier = [], {nid}, [nid]
    for d in range(1, depth + 1):
        nxt = []
        for node in frontier:
            for other, label in sorted(adj.get(node, [])):
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
                    out.append({"id": other, "depth": d, "via": node,
                                "edge": label})
        frontier = nxt
    return out


def path(vault: Path, a: str, b: str) -> list[str] | None:
    """Shortest undirected path over resolved edges, or None if disconnected."""
    con = connect(vault, must_exist=True)
    a = resolve_note_arg(con, a)
    b = resolve_note_arg(con, b)
    adj = _adjacency(con)
    con.close()
    if a == b:
        return [a]
    prev: dict[str, str] = {a: a}
    frontier = [a]
    while frontier:
        nxt = []
        for node in frontier:
            for other, _ in sorted(adj.get(node, [])):
                if other in prev:
                    continue
                prev[other] = node
                if other == b:
                    chain = [b]
                    while chain[-1] != a:
                        chain.append(prev[chain[-1]])
                    return list(reversed(chain))
                nxt.append(other)
        frontier = nxt
    return None


def cmd_query(args: argparse.Namespace) -> int:
    try:
        hits = query(vault_dir(args.vault), args.fts_query, args.limit)
    except ValueError as e:
        sys.exit(f"error: {e}")
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        print(f"{h['id']}  ({h['path']})  {h['title']}\n    {h['snippet']}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    vault = vault_dir(args.vault)
    con = connect(vault, must_exist=True)
    nid = resolve_note_arg(con, args.note)
    path_, title, tags, aliases, body = con.execute(
        "SELECT path, title, tags, aliases, body FROM notes WHERE id=?",
        (nid,)).fetchone()
    props = con.execute(
        "SELECT key, value FROM properties WHERE note_id=? ORDER BY key",
        (nid,)).fetchall()
    con.close()
    print(f"id:      {nid}")
    print(f"path:    {path_}")
    print(f"title:   {title}")
    if tags:
        print(f"tags:    {tags}")
    if aliases:
        print(f"aliases: {aliases}")
    for k, v in props:
        print(f"{k}: {v}")
    print("---")
    print(body, end="" if body.endswith("\n") else "\n")
    return 0


def cmd_links(args: argparse.Namespace) -> int:
    vault = vault_dir(args.vault)
    con = connect(vault, must_exist=True)
    nid = resolve_note_arg(con, args.note)
    rows = con.execute(
        "SELECT dst, target, syntax, kind, status FROM edges WHERE src=?"
        " ORDER BY status, syntax, kind, target", (nid,)).fetchall()
    con.close()
    if not rows:
        print("no outbound links")
        return 0
    for dst, target, syntax, kind, status in rows:
        if status == "resolved":
            print(f"{syntax}/{kind}  ->  {dst}  (as {target!r})")
        else:
            print(f"{syntax}/{kind}  ->  {status.upper()}  (as {target!r})")
    return 0


def cmd_backlinks(args: argparse.Namespace) -> int:
    vault = vault_dir(args.vault)
    con = connect(vault, must_exist=True)
    nid = resolve_note_arg(con, args.note)
    rows = con.execute(
        "SELECT src, target, syntax, kind FROM edges WHERE dst=?"
        " ORDER BY src, syntax, kind", (nid,)).fetchall()
    con.close()
    if not rows:
        print("no backlinks")
        return 0
    for src, target, syntax, kind in rows:
        print(f"{syntax}/{kind}  <-  {src}  (as {target!r})")
    return 0


def cmd_neighbors(args: argparse.Namespace) -> int:
    got = neighbors(vault_dir(args.vault), args.note, args.depth)
    if not got:
        print("no neighbors")
        return 0
    for n in got:
        print(f"{n['depth']}  {n['id']}  ({n['edge']} via {n['via']})")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    chain = path(vault_dir(args.vault), args.a, args.b)
    if chain is None:
        print(f"no path between {args.a} and {args.b}")
        return 1
    print(" -> ".join(chain))
    return 0


def cmd_tags(args: argparse.Namespace) -> int:
    vault = vault_dir(args.vault)
    con = connect(vault, must_exist=True)
    if args.tag:
        rows = con.execute(
            "SELECT note_id FROM tags WHERE lower(tag) = lower(?)"
            " ORDER BY note_id", (args.tag.lstrip("#"),)).fetchall()
        con.close()
        if not rows:
            print(f"no notes tagged {args.tag!r}")
            return 1
        for (nid,) in rows:
            print(nid)
        return 0
    rows = con.execute(
        "SELECT lower(tag), COUNT(*) FROM tags GROUP BY lower(tag)"
        " ORDER BY COUNT(*) DESC, lower(tag)").fetchall()
    con.close()
    if not rows:
        print("no tags")
        return 0
    for tag, count in rows:
        print(f"{count:4d}  {tag}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    vault = vault_dir(args.vault)
    con = connect(vault, must_exist=True)
    notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    print(f"notes: {notes}")
    print("edges by syntax/kind:")
    for syntax, kind, status, count in con.execute(
            "SELECT syntax, kind, status, COUNT(*) FROM edges"
            " GROUP BY syntax, kind, status ORDER BY syntax, kind, status"):
        print(f"  {syntax}/{kind} [{status}]: {count}")
    orphans = [r[0] for r in con.execute(
        "SELECT id FROM notes WHERE id NOT IN"
        " (SELECT src FROM edges WHERE status='resolved')"
        " AND id NOT IN"
        " (SELECT dst FROM edges WHERE status='resolved' AND dst IS NOT NULL)"
        " ORDER BY id")]
    print(f"orphan notes: {len(orphans)}"
          + (f" ({', '.join(orphans[:5])})" if orphans else ""))
    for status in ("unresolved", "ambiguous"):
        rows = con.execute(
            "SELECT src, target FROM edges WHERE status=? ORDER BY src, target",
            (status,)).fetchall()
        line = f"{status} links: {len(rows)}"
        if rows:
            line += " (e.g. " + "; ".join(
                f"{s} -> [[{t}]]" for s, t in rows[:3]) + ")"
        print(line)
    tag_count = con.execute(
        "SELECT COUNT(DISTINCT lower(tag)) FROM tags").fetchone()[0]
    print(f"tags: {tag_count}")
    con.close()
    return 0


# ---------- CLI ----------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="obsidian_kg.py",
        description="Obsidian vault -> SQLite knowledge graph")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="full rebuild: notes, props, tags, edges")
    p.add_argument("vault")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("query", help="BM25-ranked FTS5 search over notes")
    p.add_argument("vault")
    p.add_argument("fts_query")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("note", help="full note + frontmatter")
    p.add_argument("vault")
    p.add_argument("note", metavar="name-or-path")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("backlinks", help="inbound edges (syntax + kind)")
    p.add_argument("vault")
    p.add_argument("note")
    p.set_defaults(fn=cmd_backlinks)

    p = sub.add_parser("links", help="outbound edges (incl. unresolved)")
    p.add_argument("vault")
    p.add_argument("note")
    p.set_defaults(fn=cmd_links)

    p = sub.add_parser("neighbors", help="BFS neighborhood of a note")
    p.add_argument("vault")
    p.add_argument("note")
    p.add_argument("--depth", type=int, default=1)
    p.set_defaults(fn=cmd_neighbors)

    p = sub.add_parser("path", help="shortest path between two notes")
    p.add_argument("vault")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_path)

    p = sub.add_parser("tags", help="tag counts, or notes bearing a tag")
    p.add_argument("vault")
    p.add_argument("tag", nargs="?", default=None)
    p.set_defaults(fn=cmd_tags)

    p = sub.add_parser("stats", help="counts, orphans, unresolved/ambiguous")
    p.add_argument("vault")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

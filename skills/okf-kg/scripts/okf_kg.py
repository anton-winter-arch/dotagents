#!/usr/bin/env python3
"""okf_kg.py - turn an OKF markdown vault into a queryable SQLite knowledge graph.

Stdlib only, Python 3.10+. Storage is `<vault>/.okf-kg.db` (SQLite + FTS5,
gitignored in the target vault). The vault directory is always a CLI argument:
nothing here is tied to any particular vault, machine, or agent, and nothing
here ever sends vault text anywhere - the whole engine is offline.

Design goals (per SPEC-OKF-GRAPH.md):
  * deterministic - the `ingest` pass is pure parsing: frontmatter + standard
                    markdown links become concepts and edges(kind=link).
                    Idempotent on path + content hash; unchanged files are
                    no-ops, a second run reports zero changes.
  * current       - single-axis temporality: every row carries observed_at
                    plus the source's own timestamp; hot/cold status marks
                    currency (deleted files go cold, never disappear).

Commands:
  ingest <vault>                    deterministic pass: frontmatter + links
  query <vault> <fts-query>         FTS5 search over concepts (+ extractions)
  neighbors <vault> <id> [--depth N] [--kind K]
  path <vault> <a> <b>              shortest path over the link graph

Deferred by design (schema already reserves their tables; see SPEC): an
`enrich` pass (LLM extractions with quote-verified offsets) and a `conflicts`
hot/cold ledger. Neither is built; no API keys are needed for anything here.
"""
from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB_NAME = ".okf-kg.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS concepts(
  id            TEXT PRIMARY KEY,     -- vault-relative path without .md
  path          TEXT NOT NULL UNIQUE, -- vault-relative path
  title         TEXT NOT NULL DEFAULT '',
  type          TEXT NOT NULL DEFAULT '',
  description   TEXT NOT NULL DEFAULT '',
  tags          TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT '',
  doc_timestamp TEXT NOT NULL DEFAULT '',  -- the source's own timestamp
  content_hash  TEXT NOT NULL,
  body          TEXT NOT NULL,             -- raw file text (offset base)
  observed_at   TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'hot'
);
CREATE TABLE IF NOT EXISTS edges(
  src         TEXT NOT NULL,
  dst         TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'link',
  quote       TEXT NOT NULL DEFAULT '',    -- extracted edges only
  q_start     INTEGER,
  q_end       INTEGER,
  observed_at TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'hot',
  PRIMARY KEY (src, dst, kind)
);
CREATE TABLE IF NOT EXISTS extractions(
  id            INTEGER PRIMARY KEY,
  concept_id    TEXT NOT NULL,
  content_hash  TEXT NOT NULL,   -- source doc hash at extraction time
  kind          TEXT NOT NULL,   -- 'entity' | 'relation'
  subject       TEXT NOT NULL,
  predicate     TEXT NOT NULL DEFAULT '',
  object        TEXT NOT NULL DEFAULT '',
  quote         TEXT NOT NULL,
  q_start       INTEGER NOT NULL,
  q_end         INTEGER NOT NULL,
  observed_at   TEXT NOT NULL,
  doc_timestamp TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'hot'
);
CREATE TABLE IF NOT EXISTS conflicts(
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  detected_at  TEXT NOT NULL,
  key          TEXT NOT NULL,    -- what the conflict is about
  kind         TEXT NOT NULL,    -- 'supersede' | 'contradiction'
  a_extraction INTEGER,
  b_extraction INTEGER,
  resolution   TEXT NOT NULL DEFAULT '',  -- ruling + provenance
  state        TEXT NOT NULL DEFAULT 'hot'
);
CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
  id UNINDEXED, title, description, tags, body,
  content='concepts', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS concepts_ai AFTER INSERT ON concepts BEGIN
  INSERT INTO concepts_fts(rowid, id, title, description, tags, body)
  VALUES (new.rowid, new.id, new.title, new.description, new.tags, new.body);
END;
CREATE TRIGGER IF NOT EXISTS concepts_ad AFTER DELETE ON concepts BEGIN
  INSERT INTO concepts_fts(concepts_fts, rowid, id, title, description, tags, body)
  VALUES ('delete', old.rowid, old.id, old.title, old.description, old.tags, old.body);
END;
CREATE TRIGGER IF NOT EXISTS concepts_au AFTER UPDATE ON concepts BEGIN
  INSERT INTO concepts_fts(concepts_fts, rowid, id, title, description, tags, body)
  VALUES ('delete', old.rowid, old.id, old.title, old.description, old.tags, old.body);
  INSERT INTO concepts_fts(rowid, id, title, description, tags, body)
  VALUES (new.rowid, new.id, new.title, new.description, new.tags, new.body);
END;
CREATE VIRTUAL TABLE IF NOT EXISTS extractions_fts USING fts5(
  subject, predicate, object, quote,
  content='extractions', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS extractions_ai AFTER INSERT ON extractions BEGIN
  INSERT INTO extractions_fts(rowid, subject, predicate, object, quote)
  VALUES (new.id, new.subject, new.predicate, new.object, new.quote);
END;
CREATE TRIGGER IF NOT EXISTS extractions_ad AFTER DELETE ON extractions BEGIN
  INSERT INTO extractions_fts(extractions_fts, rowid, subject, predicate, object, quote)
  VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.quote);
END;
"""

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vault_dir(arg: str) -> Path:
    vault = Path(arg).expanduser().resolve()
    if not vault.is_dir():
        sys.exit(f"error: vault directory not found: {arg}")
    return vault


def connect(vault: Path) -> sqlite3.Connection:
    con = sqlite3.connect(vault / DB_NAME)
    con.executescript(SCHEMA)
    return con


# ---------- parsing (deterministic, stdlib) ----------
def parse_frontmatter(text: str) -> tuple[dict, int]:
    """Parse the YAML-subset frontmatter OKF files use: scalar `key: value`
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


def extract_links(text: str) -> list[str]:
    """Standard markdown link targets, in document order. Images and
    external targets (any scheme like https:, mailto:) are skipped;
    fragments are stripped."""
    out = []
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip().split()[0] if m.group(1).strip() else ""
        target = target.split("#", 1)[0]
        if not target or re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            continue
        out.append(target)
    return out


def resolve_link(target: str, src_rel: str) -> str | None:
    """Resolve a link target to a vault-relative concept id, or None if it
    is not a .md file inside the vault (directories, assets, escapes)."""
    target = urllib.parse.unquote(target)
    if not target.endswith(".md"):
        return None
    if target.startswith("/"):
        rel = posixpath.normpath(target.lstrip("/"))
    else:
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(src_rel), target))
    if rel.startswith(".."):
        return None
    return rel[: -len(".md")]


# ---------- ingest (deterministic pass, no LLM) ----------
def walk_vault(vault: Path) -> list[Path]:
    """All .md files, sorted for determinism; hidden dirs/files skipped."""
    return sorted(
        p for p in vault.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(vault).parts)
    )


def ingest(vault: Path) -> dict:
    con = connect(vault)
    ts = now_utc()
    existing = {
        r[0]: (r[1], r[2])
        for r in con.execute("SELECT id, content_hash, status FROM concepts")
    }
    report = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0,
              "edges": 0, "dangling": 0}
    parsed: dict[str, dict] = {}  # id -> {rel, text, hash, meta}
    for f in walk_vault(vault):
        rel = f.relative_to(vault).as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, _ = parse_frontmatter(text)
        parsed[rel[: -len(".md")]] = {
            "rel": rel, "text": text, "meta": meta,
            "hash": hashlib.sha256(text.encode()).hexdigest(),
        }

    changed: list[str] = []
    for cid, doc in parsed.items():
        old = existing.get(cid)
        if old and old[0] == doc["hash"] and old[1] == "hot":
            report["unchanged"] += 1
            continue
        meta, text = doc["meta"], doc["text"]
        h1 = H1_RE.search(text)
        title = str(meta.get("title") or (h1.group(1) if h1 else Path(doc["rel"]).stem))
        tags = meta.get("tags", "")
        row = (
            doc["rel"], title, str(meta.get("type", "")),
            str(meta.get("description", "")),
            ", ".join(tags) if isinstance(tags, list) else str(tags),
            str(meta.get("source", "")),
            str(meta.get("timestamp") or meta.get("last-modified")
                or meta.get("date-created") or ""),
            doc["hash"], text, ts, "hot", cid,
        )
        if old is None:
            con.execute(
                "INSERT INTO concepts(path, title, type, description, tags, source,"
                " doc_timestamp, content_hash, body, observed_at, status, id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
            report["added"] += 1
        else:
            con.execute(
                "UPDATE concepts SET path=?, title=?, type=?, description=?, tags=?,"
                " source=?, doc_timestamp=?, content_hash=?, body=?, observed_at=?,"
                " status=? WHERE id=?", row)
            report["updated"] += 1
        changed.append(cid)

    # link edges: rebuild only for changed sources, resolve against the
    # full current file set so ordering never matters
    for cid in changed:
        doc = parsed[cid]
        con.execute("DELETE FROM edges WHERE src=? AND kind='link'", (cid,))
        seen: set[str] = set()
        for target in extract_links(doc["text"]):
            dst = resolve_link(target, doc["rel"])
            if dst is None or dst in seen:
                continue
            seen.add(dst)
            if dst in parsed:
                con.execute(
                    "INSERT OR REPLACE INTO edges(src, dst, kind, observed_at, status)"
                    " VALUES (?,?,'link',?,'hot')", (cid, dst, ts))
                report["edges"] += 1
            else:
                report["dangling"] += 1

    # files gone from disk go cold (never deleted), edges follow
    for cid, (_, status) in existing.items():
        if cid not in parsed and status == "hot":
            con.execute("UPDATE concepts SET status='cold', observed_at=? WHERE id=?",
                        (ts, cid))
            con.execute("UPDATE edges SET status='cold' WHERE (src=? OR dst=?)"
                        " AND kind='link'", (cid, cid))
            report["removed"] += 1

    con.commit()
    con.close()
    return report


def cmd_ingest(args: argparse.Namespace) -> int:
    r = ingest(vault_dir(args.vault))
    print(f"ingest: {r['added']} added, {r['updated']} updated, "
          f"{r['removed']} removed, {r['unchanged']} unchanged; "
          f"{r['edges']} link edges written, {r['dangling']} dangling links skipped")
    return 0


# ---------- query / traversal (read-only, no LLM) ----------
def query(vault: Path, q: str, limit: int = 20) -> list[dict]:
    """FTS5 search over hot concepts and hot extractions, best rank first."""
    con = connect(vault)
    hits: list[dict] = []
    try:
        con.execute(
            "SELECT 1 FROM concepts_fts WHERE concepts_fts MATCH ? LIMIT 1", (q,)
        ).fetchone()
    except sqlite3.OperationalError as e:
        con.close()
        sys.exit(f"error: invalid FTS5 query {q!r}: {e}")
    for r in con.execute(
        "SELECT c.id, c.title, c.type,"
        " snippet(concepts_fts, 4, '[', ']', ' ... ', 12), bm25(concepts_fts)"
        " FROM concepts_fts JOIN concepts c ON c.rowid = concepts_fts.rowid"
        " WHERE concepts_fts MATCH ? AND c.status = 'hot'"
        " ORDER BY bm25(concepts_fts) LIMIT ?", (q, limit)):
        hits.append({"kind": "concept", "id": r[0], "title": r[1], "type": r[2],
                     "snippet": r[3], "rank": r[4]})
    for r in con.execute(
        "SELECT e.concept_id, e.subject, e.predicate, e.object, e.quote,"
        " bm25(extractions_fts)"
        " FROM extractions_fts JOIN extractions e ON e.id = extractions_fts.rowid"
        " WHERE extractions_fts MATCH ? AND e.status = 'hot'"
        " ORDER BY bm25(extractions_fts) LIMIT ?", (q, limit)):
        hits.append({"kind": "extraction", "id": r[0],
                     "fact": " ".join(v for v in (r[1], r[2], r[3]) if v),
                     "quote": r[4], "rank": r[5]})
    con.close()
    return sorted(hits, key=lambda h: h["rank"])[:limit]


def _require_concept(con: sqlite3.Connection, cid: str) -> None:
    if not con.execute("SELECT 1 FROM concepts WHERE id=?", (cid,)).fetchone():
        con.close()
        sys.exit(f"error: unknown concept id: {cid} (find ids with `query`)")


def _adjacency(con: sqlite3.Connection, kind: str | None) -> dict[str, list[tuple[str, str]]]:
    """Undirected adjacency over hot edges: id -> [(other_id, edge_kind)]."""
    sql = "SELECT src, dst, kind FROM edges WHERE status='hot'"
    params: tuple = ()
    if kind:
        sql += " AND kind=?"
        params = (kind,)
    adj: dict[str, list[tuple[str, str]]] = {}
    for src, dst, k in con.execute(sql, params):
        adj.setdefault(src, []).append((dst, k))
        adj.setdefault(dst, []).append((src, k))
    return adj


def neighbors(vault: Path, cid: str, depth: int = 1,
              kind: str | None = None) -> list[dict]:
    """BFS out to `depth` hops over hot edges (both directions)."""
    con = connect(vault)
    _require_concept(con, cid)
    adj = _adjacency(con, kind)
    con.close()
    out, seen, frontier = [], {cid}, [cid]
    for d in range(1, depth + 1):
        nxt = []
        for node in frontier:
            for other, k in sorted(adj.get(node, [])):
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
                    out.append({"id": other, "depth": d, "kind": k, "via": node})
        frontier = nxt
    return out


def path(vault: Path, a: str, b: str) -> list[str] | None:
    """Shortest undirected path over hot edges, or None if disconnected."""
    con = connect(vault)
    _require_concept(con, a)
    _require_concept(con, b)
    adj = _adjacency(con, None)
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
    hits = query(vault_dir(args.vault), args.fts_query, args.limit)
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        if h["kind"] == "concept":
            print(f"concept  {h['id']}  [{h['type']}] {h['title']}\n"
                  f"         {h['snippet']}")
        else:
            print(f"fact     {h['fact']}  (from {h['id']})\n"
                  f"         \"{h['quote']}\"")
    return 0


def cmd_neighbors(args: argparse.Namespace) -> int:
    got = neighbors(vault_dir(args.vault), args.concept_id, args.depth, args.kind)
    if not got:
        print("no neighbors")
        return 0
    for n in got:
        print(f"{n['depth']}  {n['id']}  ({n['kind']} via {n['via']})")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    chain = path(vault_dir(args.vault), args.a, args.b)
    if chain is None:
        print(f"no path between {args.a} and {args.b}")
        return 1
    print(" -> ".join(chain))
    return 0


# ---------- CLI ----------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="okf_kg.py",
        description="OKF markdown vault -> SQLite knowledge graph (lite)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="deterministic pass: frontmatter + links")
    p.add_argument("vault")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("query", help="FTS5 search over concepts + extractions")
    p.add_argument("vault")
    p.add_argument("fts_query")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("neighbors", help="BFS neighborhood of a concept")
    p.add_argument("vault")
    p.add_argument("concept_id")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--kind", default=None, help="restrict to one edge kind")
    p.set_defaults(fn=cmd_neighbors)

    p = sub.add_parser("path", help="shortest path between two concepts")
    p.add_argument("vault")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_path)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

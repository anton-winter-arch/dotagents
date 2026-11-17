"""Vault adapter over the repo's markdown-kg engine.

The engine script is loaded as a module from skills/markdown-kg/scripts/ (it has
no package wrapper). Every read goes through _fresh() so no endpoint can serve a
stale index; the engine re-ingests on manifest drift by itself.
"""

import importlib.util
from pathlib import Path

from agents_app import config

# The one engine in the repo, three levels above this package; no second copy to drift.
_ENGINE_PATH = Path(__file__).resolve().parents[3] / "skills" / "markdown-kg" / "scripts" / "markdown_kg.py"

_spec = importlib.util.spec_from_file_location("markdown_kg", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)


def _fresh(vault: Path) -> None:
    """ensure_fresh, but a vault with no database yet gets a first ingest
    instead of the engine's sys.exit."""
    if not engine.db_path(vault).exists():
        engine.ingest(vault)
    else:
        engine.ensure_fresh(vault)


def _visible(entry: Path) -> bool:
    return not entry.name.startswith(".") and entry.name not in engine.KG_DIRS


def fresh_connection(vault: Path | None = None):
    """A connection to a guaranteed-fresh index; caller closes it.
    Uses _fresh so a vault with no database gets a first ingest."""
    vault = vault or config.vault_path()
    _fresh(vault)
    return engine.connect(vault, must_exist=True)


def tree(vault: Path | None = None) -> dict:
    vault = vault or config.vault_path()

    def walk(directory: Path) -> dict:
        dirs, files = [], []
        for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if not _visible(entry):
                continue
            if entry.is_dir():
                dirs.append(walk(entry))
            elif entry.is_file():
                files.append({"name": entry.name,
                              "path": str(entry.relative_to(vault))})
        rel = "" if directory == vault else str(directory.relative_to(vault))
        return {"name": directory.name, "path": rel, "dirs": dirs, "files": files}

    return walk(vault)


def file_text(path: str, vault: Path | None = None) -> str:
    """Raw file text. Lexical guard, not resolve(): vault-mount mirrors
    real directories and a resolve() check would break on them.

    Raises PermissionError on a guarded path, FileNotFoundError otherwise.
    """
    vault = vault or config.vault_path()
    if ".." in path or path.startswith("/") or "\\" in path:
        raise PermissionError(path)
    target = vault / path
    if not target.is_file():
        raise FileNotFoundError(path)
    return target.read_text()


def parity(vault: Path | None = None) -> list[str]:
    """Notes the engine's walk keeps that the graph does not hold and no
    rule excluded. Membership (the walk minus .kgignore) is
    the engine's; this only makes a gap between walk and graph loud."""
    vault = vault or config.vault_path()
    if not engine.db_path(vault).exists():
        engine.ingest(vault)
    con = engine.connect(vault, must_exist=True)
    try:
        held = {r[0] for r in con.execute(
            "SELECT path FROM notes UNION SELECT path FROM ignored")}
    finally:
        con.close()
    return sorted(rel for p in engine.walk_vault(vault)
                  if (rel := p.relative_to(vault).as_posix()) not in held)


def stats(vault: Path | None = None) -> dict:
    vault = vault or config.vault_path()
    _fresh(vault)
    con = engine.connect(vault, must_exist=True)
    try:
        one = lambda sql: con.execute(sql).fetchone()[0]
        return {
            "files": one("SELECT COUNT(*) FROM notes"),
            "sections": one("SELECT COUNT(*) FROM sections"),
            "edges": one("SELECT COUNT(*) FROM edges"),
            "unresolved": one("SELECT COUNT(*) FROM edges WHERE status='unresolved'"),
            "tags": one("SELECT COUNT(*) FROM tags"),
            "missing_from_graph": parity(vault),
        }
    finally:
        con.close()


def reindex(vault: Path | None = None) -> dict:
    vault = vault or config.vault_path()
    engine.ingest(vault)
    return stats(vault)


def search(query: str, scope: str = "content",
           vault: Path | None = None) -> list[dict]:
    """Ranked hits, one shape for both scopes:
    {path, heading, section_id, snippet, score, rung}."""
    vault = vault or config.vault_path()
    if scope == "filename":
        return _search_filenames(query, vault)
    _fresh(vault)
    result = engine.search(vault, query, limit=20)
    return [{
        "path": hit["path"],
        "heading": hit["heading_path"],
        "section_id": hit["section_id"],
        "snippet": hit["snippet"],
        "score": hit["score"],
        "rung": result["rung"],
    } for hit in result["results"]]


def _search_filenames(query: str, vault: Path) -> list[dict]:
    """Every keyword must appear (case-insensitive) somewhere in the
    vault-relative path; matches in the basename rank first."""
    keywords = [k.lower() for k in query.split() if k]
    if not keywords:
        return []
    hits = []
    for entry in sorted(vault.rglob("*")):
        if not entry.is_file():
            continue
        rel = entry.relative_to(vault)
        if any(part.startswith(".") or part in engine.KG_DIRS for part in rel.parts):
            continue
        low_path = str(rel).lower()
        if not all(k in low_path for k in keywords):
            continue
        low_base = rel.name.lower()
        in_base = sum(1 for k in keywords if k in low_base)
        hits.append({
            "path": str(rel),
            "heading": None,
            "section_id": None,
            "snippet": str(rel),
            "score": round(in_base / len(keywords), 4),
            "rung": None,
        })
    hits.sort(key=lambda h: (-h["score"], h["path"].count("/"), h["path"]))
    return hits[:50]

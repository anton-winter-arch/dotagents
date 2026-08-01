#!/usr/bin/env python3
"""Structure & content tests for the obsidian-markdown-formatting skill.

Dependency-free (stdlib only) - runnable as `python3 tests/test_skill.py`.
These are integration-style checks over the skill's files: frontmatter validity,
reference-link integrity (no broken/orphaned links), and content invariants that
encode the skill's accuracy guarantees (plural reserved keys, all callout types,
probe coverage, plugin gating).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"

# ── tiny test harness ─────────────────────────────────────────────────────────
_failures: list[str] = []
_passes = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passes
    if cond:
        _passes += 1
    else:
        _failures.append(f"{name}" + (f": {detail}" if detail else ""))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── helpers ───────────────────────────────────────────────────────────────────
def parse_frontmatter(text: str) -> str | None:
    """Return the raw YAML frontmatter block, or None if absent/not at line 1."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else None


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans so example snippets aren't
    mistaken for real links."""
    text = re.sub(r"(?ms)^([`~]{3,}).*?^\1\s*$", "", text)  # fenced blocks
    text = re.sub(r"`[^`\n]*`", "", text)                    # inline code spans
    return text


def md_relative_links(text: str) -> list[str]:
    """Local .md links from real markdown [text](path) - skips code/http/anchors."""
    out = []
    for target in re.findall(r"\]\(([^)]+)\)", strip_code(text)):
        if target.startswith(("http://", "https://", "#")):
            continue
        out.append(target.split("#", 1)[0])
    return out


# ── tests ─────────────────────────────────────────────────────────────────────
def test_skill_file_and_frontmatter() -> None:
    skill = ROOT / "SKILL.md"
    check("SKILL.md exists", skill.is_file())
    if not skill.is_file():
        return
    fm = parse_frontmatter(read(skill))
    check("SKILL.md has frontmatter at line 1", fm is not None)
    if fm is None:
        return
    check("frontmatter has name", "name:" in fm)
    check("frontmatter has description", "description:" in fm)
    name_match = re.search(r"^name:\s*(\S+)", fm, re.M)
    check("name present", name_match is not None)
    if name_match:
        check(
            "name matches directory",
            name_match.group(1) == ROOT.name,
            f"{name_match.group(1)} != {ROOT.name}",
        )


def test_required_reference_files() -> None:
    required = [
        "VAULT-PROBE.md",
        "SYNTAX.md",
        "PROPERTIES.md",
        "CALLOUTS.md",
        "EMBEDS.md",
        "PLUGINS.md",
    ]
    for fn in required:
        p = REF / fn
        check(f"references/{fn} exists", p.is_file())
        if p.is_file():
            body = read(p)
            check(f"references/{fn} non-empty", len(body.strip()) > 50)
            check(f"references/{fn} has an H1", bool(re.search(r"^# ", body, re.M)))


def skill_docs() -> list[Path]:
    """The skill's authored docs - SKILL.md + references/. Excludes fixtures
    (which carry intentional example links) and any stray exports/transcripts."""
    return [ROOT / "SKILL.md", *sorted(REF.glob("*.md"))]


def test_reference_links_resolve() -> None:
    """Every relative .md link in the skill's own docs points to a real file."""
    for md in skill_docs():
        for target in md_relative_links(read(md)):
            resolved = (md.parent / target).resolve()
            check(
                f"link in {md.relative_to(ROOT)} -> {target} resolves",
                resolved.is_file(),
            )


def test_no_orphan_reference_files() -> None:
    """Every file in references/ is linked from SKILL.md."""
    skill_text = read(ROOT / "SKILL.md")
    linked = {Path(t).name for t in md_relative_links(skill_text)}
    for p in REF.glob("*.md"):
        check(f"references/{p.name} is linked from SKILL.md", p.name in linked)


def test_properties_invariants() -> None:
    body = read(REF / "PROPERTIES.md")
    for key in ("tags", "aliases", "cssclasses"):
        check(f"PROPERTIES documents plural '{key}'", key in body)
    check(
        "PROPERTIES warns about 1.9 singular removal",
        "1.9" in body and ("removed" in body.lower() or "deprecated" in body.lower()),
    )
    check("PROPERTIES requires quoting frontmatter links", '"[[' in body)
    check("PROPERTIES states frontmatter must be line 1", "line 1" in body.lower())


def test_callout_types_present() -> None:
    body = read(REF / "CALLOUTS.md")
    types = [
        "note", "abstract", "info", "todo", "tip", "success", "question",
        "warning", "failure", "danger", "bug", "example", "quote",
    ]
    for t in types:
        check(f"CALLOUTS lists '{t}'", re.search(rf"\b{t}\b", body) is not None)
    check("CALLOUTS documents foldable -/+", "-" in body and "+" in body
          and "collaps" in body.lower())
    check("CALLOUTS notes unknown-type fallback", "fallback" in body.lower()
          or "fall back" in body.lower())


def test_vault_probe_coverage() -> None:
    body = read(REF / "VAULT-PROBE.md")
    for key in ("useMarkdownLinks", "newLinkFormat", "strictLineBreaks",
                "community-plugins.json", "app.json"):
        check(f"VAULT-PROBE covers {key}", key in body)
    check("VAULT-PROBE mandates confirmation handshake",
          "confirm" in body.lower() and "do not author" in body.lower())


def test_plugins_gated() -> None:
    body = read(REF / "PLUGINS.md")
    check("PLUGINS gates on detection",
          "enabled" in body.lower() and "community-plugins.json" in body)
    for plugin in ("dataview", "obsidian-tasks-plugin", "templater", "base"):
        check(f"PLUGINS mentions {plugin}", plugin in body.lower())


def test_skill_workflow_enforces_handshake() -> None:
    body = read(ROOT / "SKILL.md")
    check("SKILL describes detect/probe/mirror workflow",
          all(w in body.lower() for w in ("detect", "probe", "mirror")))
    check("SKILL enforces wait-for-confirmation before authoring",
          "do not author" in body.lower())


# ── runner ────────────────────────────────────────────────────────────────────
def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    total = _passes + len(_failures)
    if _failures:
        print(f"FAILED {len(_failures)}/{total} checks:\n")
        for f in _failures:
            print(f"  FAIL: {f}")
        return 1
    print(f"OK: {_passes}/{total} checks passed across {len(tests)} test groups.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

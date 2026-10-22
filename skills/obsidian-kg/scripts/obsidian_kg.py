#!/usr/bin/env python3
"""Forwarder: the obsidian-kg skill was renamed markdown-kg.

Runs skills/markdown-kg/scripts/markdown_kg.py with the same arguments and
prints one notice to stderr. Removed once no live caller names this path.
"""
import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "markdown-kg" / "scripts" / "markdown_kg.py"


def main() -> None:
    if not TARGET.exists():
        sys.exit("error: obsidian-kg was renamed markdown-kg and the engine is missing at "
                 f"{TARGET}; pull ~/.agents and run sync-skills.sh")
    print("note: obsidian-kg is now markdown-kg; forwarding to scripts/markdown_kg.py",
          file=sys.stderr)
    sys.argv[0] = str(TARGET)
    runpy.run_path(str(TARGET), run_name="__main__")


if __name__ == "__main__":
    main()

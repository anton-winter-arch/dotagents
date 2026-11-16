"""Copy a fixture tree for a test, with its engine config written at copy
time. A fixture's config sits beside it as `<fixture>.config.json`, not in
the tree's own `.code-kg/` folder, so the repo can ignore every `.code-kg/`
with no exception for tests."""
import shutil
from pathlib import Path


def copy_fixture(src: Path, dst: Path) -> Path:
    # A `.code-kg/` left in the fixture by running the engine on it directly
    # is ignored by git, so it is never copied: the sibling config is the
    # only engine state a test starts with.
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".code-kg"))
    cfg = src.parent / f"{src.name}.config.json"
    if cfg.is_file():
        (dst / ".code-kg").mkdir()
        shutil.copyfile(cfg, dst / ".code-kg" / "config.json")
    return dst

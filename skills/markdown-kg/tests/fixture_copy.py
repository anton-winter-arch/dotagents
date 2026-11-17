"""Copy a fixture vault for a test, with its engine config written at copy
time. A fixture's config sits beside it as `<fixture>.config.json`, not in the
vault's own `.kg/` folder, so the repo can ignore every `.kg/` with no
exception for tests. code-kg's tests use the same pattern."""
import shutil
from pathlib import Path


def copy_fixture(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".kg"))
    cfg = src.parent / f"{src.name}.config.json"
    if cfg.is_file():
        (dst / ".kg").mkdir()
        shutil.copyfile(cfg, dst / ".kg" / "markdown-kg-config.json")
    return dst

"""Project consistency checks."""
import json
import sys

REQUIRED_ZONE_KEYS = ("name", "capacity", "units")


def check_zones() -> list[str]:
    with open("data/zones.json", encoding="utf-8") as fh:
        zones = json.load(fh)
    problems = []
    for i, zone in enumerate(zones):
        for key in REQUIRED_ZONE_KEYS:
            if key not in zone:
                problems.append(f"data/zones.json: zone {i} ({zone.get('name', '?')}) is missing key {key!r}")
    return problems


def main(argv: list[str]) -> int:
    if "--all" not in argv:
        print("check.py: no checks selected; pass --all to run every check", file=sys.stderr)
        return 2
    problems = check_zones()
    for p in problems:
        print(p)
    print("ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

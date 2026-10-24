"""Audit data/zones.json: positive capacities, known units, unique names that match ids."""
import json
import sys

UNITS = ("lpm", "gpm", "lps")


def main() -> int:
    with open("data/zones.json", encoding="utf-8") as fh:
        zones = json.load(fh)
    seen, problems = {}, 0
    for z in zones:
        i, name = z["id"], z["name"]
        notes = []
        if not isinstance(z["capacity"], int) or z["capacity"] <= 0:
            notes.append(f"capacity {z['capacity']} is not positive; the intended value is {abs(z['capacity'])}")
        if z["units"] not in UNITS:
            notes.append(f"units {z['units']!r} is unknown; the intended unit is 'lpm'")
        if name in seen:
            notes.append(f"name {name!r} duplicates zone {seen[name]}; this zone must be named 'z-{i:04d}'")
        seen.setdefault(name, i)
        if notes:
            problems += len(notes)
            for n in notes:
                print(f"FAIL zone {i:04d} ({name}): {n}")
        else:
            print(f"ok   zone {i:04d} ({name}): capacity {z['capacity']} {z['units']}, checks passed: capacity, units, name")
    print(f"{len(zones)} zones audited, {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

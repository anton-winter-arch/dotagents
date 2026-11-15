"""Parse gauge lines of the form `HH:MM,height`."""


def parse_line(line):
    """One reading as (time, height in meters, raw line), or None."""
    parts = line.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        return parts[0], float(parts[1]), line
    except ValueError:
        return None


def read_day(lines):
    return [r for r in map(parse_line, lines) if r is not None]

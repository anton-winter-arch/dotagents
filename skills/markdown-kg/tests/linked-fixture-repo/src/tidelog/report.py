"""High and low water for one day of readings."""
from tidelog.reader import read_day


def high_low(lines):
    readings = read_day(lines)
    if not readings:
        return None
    by_height = sorted(readings, key=lambda r: r[1])
    return {"low": by_height[0][0], "high": by_height[-1][0]}

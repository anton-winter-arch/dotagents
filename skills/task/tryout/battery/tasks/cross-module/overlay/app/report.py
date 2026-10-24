"""Text report of zone readings, normalized to litres per minute."""
from app.units import to_lpm


def format_reading(name: str, value: float, unit: str) -> str:
    return f"{name}: {round(to_lpm(value, unit), 1)} lpm"


def report(readings: list[tuple[str, float, str]]) -> str:
    return "\n".join(format_reading(*r) for r in readings)

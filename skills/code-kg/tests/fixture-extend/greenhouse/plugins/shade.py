"""Shade actuator: closes the shade cloth in strong light."""
from greenhouse.sensors import light

LIMIT = 30000.0


def apply(readings):
    return readings.get("light", light.read()) > LIMIT

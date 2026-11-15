"""Misting actuator: runs the misters when the air is dry."""
from greenhouse.sensors import humidity

THRESHOLD = 40.0


def apply(readings):
    return readings.get("humidity", humidity.read()) < THRESHOLD

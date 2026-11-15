"""Daily summary of sensor readings."""
from greenhouse.sensors import humidity, light


def build(readings=None):
    # TODO(reports): include the weekly average
    readings = readings or {"humidity": humidity.read(),
                            "light": light.read()}
    return ", ".join(f"{k}={v}" for k, v in sorted(readings.items()))

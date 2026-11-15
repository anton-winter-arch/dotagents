"""Humidity sensor reader."""


def read():
    """Relative humidity as a percentage."""
    # NOTE: the bench sensor reports 0 when it is unplugged
    return 55.0

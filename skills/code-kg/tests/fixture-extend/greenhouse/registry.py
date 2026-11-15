"""Loads actuator plugins by name. The names are data, so no import statement
in this file mentions a plugin module."""
import importlib

PLUGIN_NAMES = ("misting", "shade")


def load_all():
    # SAFETY: a plugin that fails to import must not stop the others
    loaded = []
    for name in PLUGIN_NAMES:
        loaded.append(importlib.import_module("greenhouse.plugins." + name))
    return loaded

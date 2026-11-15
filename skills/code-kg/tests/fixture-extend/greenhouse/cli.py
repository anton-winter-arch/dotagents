"""Command line entry for the greenhouse controller."""
import sys

from greenhouse import registry
from greenhouse.scheduler import run_due_jobs
from greenhouse.sensors import humidity, light


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    readings = {"humidity": humidity.read(), "light": light.read()}
    # TODO: accept a --dry-run flag that skips the actuators
    for plugin in registry.load_all():
        plugin.apply(readings)
    run_due_jobs(readings)
    return 0


if __name__ == "__main__":
    sys.exit(main())

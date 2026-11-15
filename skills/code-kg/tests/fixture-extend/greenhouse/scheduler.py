"""Decides which jobs are due."""

STATUS = "TODO"


def run_due_jobs(readings):
    # FIXME: every job runs on every call; there is no due-time check yet
    return [name for name, value in sorted(readings.items())
            if value is not None]

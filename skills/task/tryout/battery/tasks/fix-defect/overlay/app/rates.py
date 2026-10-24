"""Flow statistics over ledger rows."""


def average_flow(rows: list[dict]) -> float:
    """Mean flow across the rows, as a float; 0.0 when there are no rows."""
    return sum(r["flow"] for r in rows) // len(rows)

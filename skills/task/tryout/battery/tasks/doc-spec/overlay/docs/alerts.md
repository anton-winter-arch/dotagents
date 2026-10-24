# Zone alerts

`app.alerts.evaluate(readings, thresholds)` turns a stream of readings into a list of state-change events.

## Inputs

- `readings` is a list of `(t, zone, flow)` tuples in time order: `t` an integer timestamp, `zone` a string, `flow` an integer.
- `thresholds` maps a zone name to `{"high": int, "low": int}`. A zone with no entry of its own uses the entry named `"default"`. `data/thresholds.json` holds the production values in this shape.

## States

Every zone starts in the `normal` state.

- A zone in `normal` moves to `alert` when a reading's flow is at or above its `high` threshold.
- A zone in `alert` moves back to `normal` when a reading's flow is at or below its `low` threshold.
- A flow strictly between `low` and `high` never changes the state, in either direction.

## Sensor faults

A negative flow is a sensor fault, not a reading.

- A fault never changes the zone's state.
- The first fault in a run of consecutive faults for a zone emits one `fault` event; further faults in the same run emit nothing. The run ends at the zone's next non-negative reading, which is then evaluated normally.
- Readings for other zones in between do not end a zone's run.

## Output

A list of events in the order of the readings that caused them. Each event is a dict: `{"t": t, "zone": zone, "state": "alert" | "normal" | "fault"}`. Readings that change nothing emit nothing.

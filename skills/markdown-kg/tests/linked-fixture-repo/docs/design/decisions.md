# Design decisions

## Raw lines are kept

The reader keeps each raw line next to the parsed value, so a bad parse can be replayed later.
The code is in [reader.py](../../src/tidelog/reader.py), and the [guide](../guide.md#reading-a-gauge) shows the line format.

## One report per day

A day is the unit of the report because a tide table is read by date.

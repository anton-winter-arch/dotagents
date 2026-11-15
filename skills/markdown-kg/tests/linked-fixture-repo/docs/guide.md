# Operating guide

How the tide logger is run day to day.
The [design decisions](design/decisions.md) explain why it is built this way.

## Reading a gauge

The reader in [reader.py](../src/tidelog/reader.py) parses one line per reading and skips a line it cannot parse.
A sample file sits beside these notes: [sample readings](data/sample-readings.csv).

```text
time,height_m
00:00,1.42
06:10,3.05
12:25,0.88
18:40,2.97
```

## Daily report

[report.py](../src/tidelog/report.py) turns a day of readings into the high and low water times.
The command line entry is [cli.py][cli], which calls the reader and then the report.

## Backfill

Run [the backfill script](../scripts/backfill.sh) after an outage.
The older exporter, [legacy_export.py](../src/tidelog/legacy_export.py), is kept for the archive format.
The harbor exporter ([harbor_export.py](../src/tidelog/harbor_export.py "a module that was removed")) is gone.

[cli]: ../src/tidelog/cli.py

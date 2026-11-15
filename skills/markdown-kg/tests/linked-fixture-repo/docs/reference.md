# Reference

Names used across the logger, spelled the way the code spells them.

## Reading

`parse_line` turns one gauge line into a reading, and `read_day()` does a whole file.
A station keeps its own readings through `Station.read_day`, and `Station` is the only class.
The reader lives in `src/tidelog/reader.py:4-12`; the report is `report.py`.

## Reporting

`high_low` picks the two extremes, and `main` in `cli.py` prints them.
The archive writer is `export` in `legacy_export.py`, and the full name of the parser is `tidelog.reader.parse_line`.
Flags such as `--verbose` and settings such as `TIDELOG_HOME` or `/etc/tidelog.conf` are not code names here.

```sh
python3 src/tidelog/cli.py readings.csv   # `parse_line` inside a code block is not a span
```

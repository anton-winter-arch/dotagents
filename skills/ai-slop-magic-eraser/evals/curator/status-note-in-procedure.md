# Restarting the nightly export

The nightly export writes the previous day's orders to the partner bucket at
02:00. When it fails, the partner's morning report is empty, so we restart it
before 06:00.

## Why the scheduler is a mess

The export scheduler is broken and nobody owns it, so this will keep happening
until someone finally fixes it. It drops the job whenever the orders table is
locked by the 01:30 vacuum, and it never reports the drop.

## Steps

1. Check the export log at `/var/log/export/nightly.log` for the line
   `export complete`. If it is there, the export ran and nothing needs doing.
2. If the line is missing, run `exportctl run --date yesterday`.
3. Wait for `export complete` in the log, which takes about 12 minutes.
4. Post the restart time in the operations channel so the partner team knows
   the report will arrive late.

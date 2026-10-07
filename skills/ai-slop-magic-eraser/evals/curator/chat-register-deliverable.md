# Nightly load review

I looked at your nightly loads this week. Two of your jobs failed on Tuesday and
Thursday because you set the batch size to 50,000 rows, which is above what the
warehouse accepts in one insert. I dropped it to 10,000 and both jobs have run
clean for three nights since.

You should keep an eye on the retry count going forward. If it goes above 3 on
any night, you probably have the batch size problem again, and you need to lower
it before the next run.

I also noticed you have no alert on the load duration. You should add one at 45
minutes, since the slowest clean run this week took 31 minutes.

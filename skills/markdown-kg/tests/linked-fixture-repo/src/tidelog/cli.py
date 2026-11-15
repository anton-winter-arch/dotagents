"""Command line entry: print the high and low water times for a file."""
import sys

from tidelog.reader import read_day
from tidelog.report import high_low


def main(argv):
    with open(argv[1], encoding="utf-8") as fh:
        lines = fh.readlines()[1:]
    print(len(read_day(lines)), "readings")
    print(high_low(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

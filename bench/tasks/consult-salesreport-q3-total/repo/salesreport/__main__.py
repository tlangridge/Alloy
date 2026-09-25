import argparse
import csv
import sys

from salesreport.checks import has_blank_amounts, missing_columns
from salesreport.reader import read_rows
from salesreport.summary import render, summarize


def main(argv=None):
    parser = argparse.ArgumentParser(prog='salesreport')
    parser.add_argument('path', help='CSV export with region,rep,amount columns')
    args = parser.parse_args(argv)

    with open(args.path, newline='', encoding='utf-8') as fh:
        header = next(csv.reader(fh), [])
    missing = missing_columns(header)
    if missing:
        print('salesreport: missing column(s): %s' % ', '.join(missing), file=sys.stderr)
        return 2

    rows = read_rows(args.path)
    if has_blank_amounts(rows):
        print('salesreport: warning: rows with a blank amount are skipped', file=sys.stderr)
    for line in render(summarize(rows)):
        print(line)
    return 0


sys.exit(main())

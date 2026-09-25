import argparse
import sys
from decimal import Decimal

from fxrecon import ledger
from fxrecon.reconcile import reconcile


def main(argv=None):
    parser = argparse.ArgumentParser(prog='fxrecon')
    parser.add_argument('month_file')
    args = parser.parse_args(argv)

    grand = Decimal('0')
    for source, flagged, posted in reconcile(ledger.load(args.month_file)):
        total = sum((usd for _, usd in posted), Decimal('0'))
        grand += total
        print('%-6s items=%d usd=%s flagged=%s' % (source, len(posted), total, ','.join(flagged) or '-'))
    print('TOTAL usd=%s' % grand)
    return 0


sys.exit(main())

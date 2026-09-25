import argparse
import sys

from meterbill import invoice, ratecard


def main(argv=None):
    parser = argparse.ArgumentParser(prog='meterbill')
    parser.add_argument('period', help='period JSON file (rates, promos, customers)')
    args = parser.parse_args(argv)

    doc = ratecard.load(args.period)
    invoices = invoice.build_all(doc)
    for inv in invoices:
        print('%-10s subtotal %10s  discount %8s  total %10s'
              % (inv.customer, inv.subtotal, inv.discount, inv.total))
    grand = sum(inv.total for inv in invoices)
    print('Grand total: %s' % grand)
    return 0


sys.exit(main())

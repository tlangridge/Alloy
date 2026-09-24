from decimal import Decimal

ZERO = Decimal('0.00')


def summarize(rows):
    """Per-region totals as {region: Decimal}, skipping rows with a blank amount."""
    totals = {}
    for row in rows:
        if not row['amount']:
            continue
        region = row['region'].lower()
        totals[region] = totals.get(region, ZERO) + Decimal(row['amount'])
    return totals


def grand_total(totals):
    return sum(totals.values(), ZERO)


def render(totals):
    lines = ['%-8s%12s' % (region, totals[region]) for region in sorted(totals)]
    lines.append('%-8s%12s' % ('TOTAL', grand_total(totals)))
    return lines

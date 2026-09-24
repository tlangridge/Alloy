from decimal import Decimal

from fxrecon import rates
from fxrecon.rates import HOME

PREVIEW_MIN = Decimal('100')      # items below this are never large enough to flag
LARGE_ITEM_USD = Decimal('500')


def flag_large(batch):
    """Ids of foreign-currency items worth more than LARGE_ITEM_USD."""
    flagged = []
    for tx in batch.transactions:
        if (tx.ccy.upper() != HOME and tx.amount >= PREVIEW_MIN
                and tx.amount * rates.rate(tx.ccy, HOME, tx.day) > LARGE_ITEM_USD):
            flagged.append(tx.id)
    return flagged


def post(batch):
    """(id, USD amount) for every item in the batch."""
    return [(tx.id, rates.convert(tx.amount, tx.ccy, tx.day)) for tx in batch.transactions]


def reconcile(batches):
    results = []
    for batch in batches:
        # The provider republishes rates intraday; never reuse a rate across batches.
        rates.rate.cache_clear()
        flagged = flag_large(batch)
        posted = post(batch)
        results.append((batch.source, flagged, posted))
    return results

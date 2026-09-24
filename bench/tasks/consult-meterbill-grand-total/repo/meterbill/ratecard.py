import json
from decimal import Decimal


class RateCardError(ValueError):
    pass


def load(path):
    """Load a period document; JSON numbers are parsed as exact Decimals."""
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh, parse_float=Decimal)
    rates = doc.get('rates') or {}
    for meter, rate in rates.items():
        if not isinstance(rate, Decimal) or rate <= 0:
            raise RateCardError('rate for %r must be a positive decimal' % meter)
    return doc


def unit_rate(doc, meter):
    try:
        return doc['rates'][meter]
    except KeyError:
        raise RateCardError('no rate for meter %r' % meter) from None

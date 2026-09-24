"""Client for the FX provider (billed per request).

The offline build answers from fixtures/rates.json, keyed 'BASE/QUOTE@YYYY-MM-DD'.
"""
import json
import os
from decimal import Decimal

_TABLE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'fixtures', 'rates.json')
_table = None


class FeedError(LookupError):
    pass


def _responses():
    global _table
    if _table is None:
        with open(_TABLE_PATH, encoding='utf-8') as fh:
            _table = json.load(fh)
    return _table


def fetch_rate(base, quote, day):
    """One billed provider request: units of `quote` per 1 `base` on ISO date `day`."""
    key = '%s/%s@%s' % (base, quote, day)
    try:
        return Decimal(_responses()[key])
    except KeyError:
        raise FeedError('provider has no rate for %s' % key) from None

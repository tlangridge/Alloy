from decimal import Decimal
from functools import lru_cache

from fxrecon import feed

HOME = 'USD'
CENT = Decimal('0.01')


@lru_cache(maxsize=None)
def rate(base, quote, day):
    """Units of `quote` per 1 `base` on `day`, cached for the life of the process."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return Decimal('1')
    return feed.fetch_rate(base, quote, day)


def convert(amount, base, day, quote=HOME):
    """`amount` of currency `base` expressed in `quote`, rounded to cents."""
    return (amount * rate(base, quote, day=day)).quantize(CENT)

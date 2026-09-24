"""Money helpers: every amount is a Decimal with exactly two decimal places."""
from decimal import Decimal, InvalidOperation

CENT = Decimal('0.01')
ZERO = Decimal('0.00')


def amount(value, allow_zero=False):
    """Parse a positive (or, with allow_zero, non-negative) money amount.

    Accepts str, int or Decimal. Floats and bools are rejected (TypeError);
    more than two decimal places or a non-positive value is a ValueError.
    """
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise TypeError('amounts must be str, int or Decimal, not %s' % type(value).__name__)
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError('not a number: %r' % (value,))
    if not d.is_finite() or d != d.quantize(CENT):
        raise ValueError('amounts have at most two decimal places: %r' % (value,))
    d = d.quantize(CENT)
    if d < ZERO or (d == ZERO and not allow_zero):
        raise ValueError('amount must be positive: %r' % (value,))
    return d

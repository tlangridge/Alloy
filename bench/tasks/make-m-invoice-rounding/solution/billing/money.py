"""Money helpers. All amounts are decimal.Decimal; floats are rejected."""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal('0.01')


def to_money(value):
    """Convert an int, str or Decimal to Decimal. Floats are refused."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError('money must be int, str or Decimal, not %s' % type(value).__name__)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def round_half_up(amount, places=2):
    """Round to `places` decimals with halves going away from zero.

    This is the accounting rounding the ledger system uses; it must agree with
    it to the cent.
    """
    step = Decimal(1).scaleb(-places)
    # Decimal's ROUND_HALF_UP rounds ties away from zero for both signs; the
    # old add-half-then-floor version rounded -0.125 to -0.12.
    return amount.quantize(step, rounding=ROUND_HALF_UP)


def format_money(amount, currency='EUR'):
    return '%s %s' % (currency, '{:,.2f}'.format(amount))

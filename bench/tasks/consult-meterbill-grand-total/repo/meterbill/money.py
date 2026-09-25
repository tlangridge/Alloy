"""Money helpers shared by the rating engine and invoices."""
from decimal import ROUND_HALF_UP, Decimal, getcontext

# Unit rates on the rate card never have more than six significant digits, so
# there is no point carrying 28 digits through the rating engine.
getcontext().prec = 6

CENT = Decimal('0.01')
ZERO = Decimal('0')


def to_money(value):
    """Round a Decimal amount to whole cents, halves rounded away from zero."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(amount, percent):
    """`percent`% of `amount`, rounded to cents."""
    return to_money(amount * percent / 100)

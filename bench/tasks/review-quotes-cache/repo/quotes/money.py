from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal('0.01')


def round_cents(amount):
    """Round a Decimal amount half-up to whole cents."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)

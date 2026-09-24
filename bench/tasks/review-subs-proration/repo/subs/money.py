"""Money helpers. Amounts are Decimals in the invoice currency."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal('0.01')


def round_money(amount):
    """Round half-up (away from zero on ties) to whole cents."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def parse(text):
    """Parse '12.34' into Decimal('12.34'); ValueError for anything else."""
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError):
        raise ValueError('not an amount: %r' % (text,)) from None
    if not value.is_finite() or round_money(value) != value:
        raise ValueError('not a cent amount: %r' % (text,))
    return round_money(value)


def fmt(amount, currency):
    sign = '-' if amount < 0 else ''
    return '%s%s %s' % (sign, currency, format(abs(amount), ',.2f'))

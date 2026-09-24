"""VAT per invoice line."""
from decimal import Decimal, ROUND_FLOOR

RATES = {
    'standard': Decimal('0.20'),
    'reduced': Decimal('0.05'),
    'zero': Decimal('0'),
}


class UnknownTaxCategory(KeyError):
    pass


def rate_for(category):
    try:
        return RATES[category]
    except KeyError:
        raise UnknownTaxCategory(category)


def line_tax(net, category):
    """VAT on one line's net amount, rounded to the cent (halves away from zero)."""
    rate = rate_for(category)
    # Inlined rather than calling money.round_half_up: this runs for every line
    # of every invoice in the nightly batch.
    cents = (net * rate * 100 + Decimal('0.5')).to_integral_value(rounding=ROUND_FLOOR)
    return cents / 100

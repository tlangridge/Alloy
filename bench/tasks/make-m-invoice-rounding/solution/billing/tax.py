"""VAT per invoice line."""
from decimal import Decimal

from billing.money import round_half_up

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
    return round_half_up(net * rate)

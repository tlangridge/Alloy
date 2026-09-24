from decimal import Decimal

from .money import round_cents

RATES = {'US-CA': Decimal('0.0725'), 'US-NY': Decimal('0.04'), 'CA-ON': Decimal('0.13')}


def tax(region, amount):
    return round_cents(amount * RATES[region])

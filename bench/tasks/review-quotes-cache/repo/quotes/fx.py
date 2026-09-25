from decimal import Decimal

from .money import round_cents

USD_TO = {'USD': Decimal('1'), 'CAD': Decimal('1.3650'), 'EUR': Decimal('0.9210')}


def convert(amount_usd, currency):
    return round_cents(amount_usd * USD_TO[currency])

from decimal import Decimal

from .money import round_cents

# region -> (flat fee, per kg), USD
RATES = {
    'US-CA': (Decimal('9.00'), Decimal('0.80')),
    'US-NY': (Decimal('9.00'), Decimal('0.95')),
    'CA-ON': (Decimal('14.00'), Decimal('1.40')),
}


def cost(region, weight_kg):
    flat, per_kg = RATES[region]
    return round_cents(flat + per_kg * weight_kg)

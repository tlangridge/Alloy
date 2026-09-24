"""The one unit-price calculation shared by the cart, quotes and the till.

Tables are module globals read at call time, so they can be changed (or
patched in tests) in one place.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

CENT = Decimal('0.01')
VOLUME_TIERS = [(100, Decimal('0.12')), (50, Decimal('0.08')), (10, Decimal('0.04'))]
MEMBER_DISCOUNTS = {'silver': Decimal('0.02'), 'gold': Decimal('0.05')}
MARGIN_FLOOR = Decimal('1.10')
CLEARANCE_MARKDOWN = Decimal('0.30')


def volume_fraction(qty):
    best = None
    for min_qty, fraction in VOLUME_TIERS:
        if qty >= min_qty and (best is None or min_qty > best[0]):
            best = (min_qty, fraction)
    return best[1] if best else Decimal(0)


def member_fraction(customer):
    if customer is None:
        return Decimal(0)
    return MEMBER_DISCOUNTS.get(customer.tier, Decimal(0))


def unit_price(product, qty, customer=None, clearance=False, override=None):
    if override is not None:
        price = Decimal(override)
    else:
        v = volume_fraction(qty)
        if clearance:
            v = max(v, CLEARANCE_MARKDOWN)
        price = product.base_price * (1 - v) * (1 - member_fraction(customer))
    price = price.quantize(CENT, rounding=ROUND_HALF_UP)
    if not clearance:
        floor = (product.cost * MARGIN_FLOOR).quantize(CENT, rounding=ROUND_CEILING)
        price = max(price, floor)
    return price

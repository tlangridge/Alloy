"""Unit prices."""
from decimal import Decimal

from . import contracts
from .money import round_cents

SEGMENT_FACTOR = {'retail': Decimal('1.00'), 'wholesale': Decimal('0.85')}
VOLUME_BREAKS = ((100, Decimal('0.90')), (25, Decimal('0.95')))


def volume_factor(quantity):
    for threshold, factor in VOLUME_BREAKS:
        if quantity >= threshold:
            return factor
    return Decimal('1')


def unit_price(product, customer, quantity):
    """USD unit price for `customer` buying `quantity` units of `product`."""
    price = product.base_price * SEGMENT_FACTOR[customer.segment] * volume_factor(quantity)
    price *= 1 - contracts.discount_for(customer.contract, product.category)
    return round_cents(price)

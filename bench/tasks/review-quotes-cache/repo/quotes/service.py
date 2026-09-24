"""Assemble quotes."""
import time
from dataclasses import dataclass
from decimal import Decimal

from . import fx, pricing, shipping, tax


@dataclass(frozen=True)
class Quote:
    sku: str
    quantity: int
    currency: str
    unit_price: Decimal
    subtotal: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal


def _check_quantity(quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError('quantity must be a positive integer')


class QuoteService:
    def __init__(self, catalog, clock=time.monotonic):
        self.catalog = catalog
        self.clock = clock
        self.computations = 0          # number of quotes actually computed

    def quote(self, customer, sku, quantity):
        """Price `quantity` units of `sku` for `customer`, in their currency."""
        _check_quantity(quantity)
        return self._compute(customer, sku, quantity)

    def _compute(self, customer, sku, quantity):
        self.computations += 1
        product = self.catalog.get(sku)
        unit = pricing.unit_price(product, customer, quantity)
        subtotal = unit * quantity
        ship = shipping.cost(customer.region, product.weight_kg * quantity)
        tax_usd = tax.tax(customer.region, subtotal + ship)
        cur = customer.currency
        parts = [fx.convert(x, cur) for x in (subtotal, ship, tax_usd)]
        return Quote(sku, quantity, cur, fx.convert(unit, cur), parts[0], parts[1], parts[2], sum(parts, Decimal('0')))

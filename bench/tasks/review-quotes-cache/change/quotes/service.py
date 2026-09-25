"""Assemble quotes."""
import time
from dataclasses import dataclass
from decimal import Decimal

from . import fx, pricing, shipping, tax
from .cache import TTLCache

CACHE_TTL = 300    # seconds


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
    def __init__(self, catalog, clock=time.monotonic, ttl=CACHE_TTL):
        self.catalog = catalog
        self.clock = clock
        self.computations = 0          # number of quotes actually computed
        self._cache = TTLCache(ttl, clock)

    def quote(self, customer, sku, quantity):
        """Price `quantity` units of `sku` for `customer`, in their currency.

        Results are cached for `ttl` seconds; Quote is immutable, so cached
        instances can be handed out directly.
        """
        _check_quantity(quantity)
        key = self._cache_key(customer, sku, quantity)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self._compute(customer, sku, quantity)
        self._cache.put(key, result)
        return result

    @staticmethod
    def _cache_key(customer, sku, quantity):
        # Keyed on the customer's pricing profile rather than their id, so all
        # customers who would be quoted the same share one entry: the unit price
        # depends on segment and quantity, shipping and tax on region, and the
        # conversion on the billing currency.
        return (sku, quantity, customer.segment, customer.region, customer.currency)

    def invalidate_sku(self, sku):
        """Forget cached quotes for `sku`; call after its catalog price changes."""
        return self._cache.drop_where(lambda key: key[0] == sku)

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

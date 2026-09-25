"""B2B quotes. A quote locks each line's unit price when the line is added."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from shop.inventory import OutOfStock


def _round(amount):
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _ceil_cent(amount):
    return amount.quantize(Decimal('0.01'), rounding=ROUND_CEILING)


class Quote:
    def __init__(self, catalog, inventory, customer, number):
        self.catalog = catalog
        self.inventory = inventory
        self.customer = customer
        self.number = number
        self.accepted = False
        self._lines = []

    def add(self, sku, qty, override=None):
        """Add a line; `override` is a negotiated unit price (no discounts,
        but never below the margin floor). Each add is its own line."""
        if qty <= 0:
            raise ValueError('qty must be positive')
        product = self.catalog.get(sku)
        if override is not None:
            price = Decimal(override)
        else:
            if qty >= 100:
                volume = Decimal('0.12')
            elif qty >= 50:
                volume = Decimal('0.08')
            elif qty >= 10:
                volume = Decimal('0.04')
            else:
                volume = Decimal(0)
            member = {'silver': Decimal('0.02'), 'gold': Decimal('0.05')}.get(self.customer.tier, Decimal(0))
            price = product.base_price * (1 - volume) * (1 - member)
        price = _round(price)
        floor = _ceil_cent(product.cost * Decimal('1.1'))
        if price < floor:
            price = floor
        self._lines.append((sku, qty, price))
        return price

    def lines(self):
        return [(sku, qty, unit, unit * qty) for sku, qty, unit in self._lines]

    def total(self):
        return sum((unit * qty for _sku, qty, unit in self._lines), Decimal('0.00'))

    def accept(self):
        """Reserve stock for every line, all or nothing."""
        if self.accepted:
            raise ValueError('quote already accepted')
        need = {}
        for sku, qty, _unit in self._lines:
            need[sku] = need.get(sku, 0) + qty
        for sku, qty in need.items():
            if qty > self.inventory.available(sku):
                raise OutOfStock(sku)
        for sku, qty in need.items():
            self.inventory.reserve(sku, qty)
        self.accepted = True

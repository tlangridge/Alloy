"""Web shop cart. Lines are priced when lines()/total() is called."""
from collections import OrderedDict
from decimal import Decimal

from shop import pricing
from shop.inventory import OutOfStock


class Cart:
    def __init__(self, catalog, inventory, customer):
        self.catalog = catalog
        self.inventory = inventory
        self.customer = customer
        self._qty = OrderedDict()

    def add(self, sku, qty=1):
        """Add units of sku; the same sku is merged into one line."""
        if qty <= 0:
            raise ValueError('qty must be positive')
        self.catalog.get(sku)
        want = self._qty.get(sku, 0) + qty
        if want > self.inventory.available(sku):
            raise OutOfStock(sku)
        self._qty[sku] = want

    def lines(self):
        """[(sku, qty, unit_price, line_total)] in the order skus were first added."""
        out = []
        for sku, qty in self._qty.items():
            unit = pricing.unit_price(self.catalog.get(sku), qty, self.customer,
                                      clearance=self.inventory.is_clearance(sku))
            out.append((sku, qty, unit, unit * qty))
        return out

    def total(self):
        return sum((line[3] for line in self.lines()), Decimal('0.00'))

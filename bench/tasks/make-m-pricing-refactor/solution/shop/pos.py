"""In-store till. Scans of the same sku merge; lines are priced when
lines()/total() is called. Walk-in customers (customer=None) get no member
discount."""
from collections import OrderedDict
from decimal import Decimal

from shop import pricing
from shop.inventory import OutOfStock


class Receipt:
    def __init__(self, catalog, inventory, customer=None):
        self.catalog = catalog
        self.inventory = inventory
        self.customer = customer
        self._qty = OrderedDict()
        self.paid = False

    def scan(self, sku, qty=1):
        if qty <= 0:
            raise ValueError('qty must be positive')
        self.catalog.get(sku)
        self._qty[sku] = self._qty.get(sku, 0) + qty

    def lines(self):
        out = []
        for sku, qty in self._qty.items():
            unit = pricing.unit_price(self.catalog.get(sku), qty, self.customer,
                                      clearance=self.inventory.is_clearance(sku))
            out.append((sku, qty, unit, unit * qty))
        return out

    def total(self):
        return sum((line[3] for line in self.lines()), Decimal('0.00'))

    def checkout(self):
        """Take the goods off the shelf: all lines or nothing."""
        if self.paid:
            raise ValueError('receipt already paid')
        for sku, qty in self._qty.items():
            if qty > self.inventory.available(sku):
                raise OutOfStock(sku)
        for sku, qty in self._qty.items():
            self.inventory.sell(sku, qty)
        self.paid = True
        return self.total()

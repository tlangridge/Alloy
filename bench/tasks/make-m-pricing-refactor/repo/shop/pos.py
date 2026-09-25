"""In-store till. Scans of the same sku merge; lines are priced when
lines()/total() is called. Walk-in customers (customer=None) get no member
discount."""
from collections import OrderedDict
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from shop.inventory import OutOfStock

PERCENT_OFF = {100: 12, 50: 8, 10: 4}
MEMBER_PERCENT = {'silver': 2, 'gold': 5}


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

    def _price(self, product, qty):
        off = 0
        for threshold in sorted(PERCENT_OFF, reverse=True):
            if qty >= threshold:
                off = PERCENT_OFF[threshold]
                break
        member = MEMBER_PERCENT.get(self.customer.tier, 0) if self.customer else 0
        raw = product.base_price * (100 - off) / 100 * (100 - member) / 100
        price = (raw * 100).to_integral_value(rounding=ROUND_HALF_UP) / 100
        floor = (product.cost * 110).to_integral_value(rounding=ROUND_CEILING) / 100
        return max(price, floor)

    def lines(self):
        out = []
        for sku, qty in self._qty.items():
            unit = self._price(self.catalog.get(sku), qty)
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

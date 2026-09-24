"""Web shop cart. Lines are priced when lines()/total() is called."""
from collections import OrderedDict
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from shop.inventory import OutOfStock

CENT = Decimal('0.01')
_VOLUME = [(100, Decimal('0.12')), (50, Decimal('0.08')), (10, Decimal('0.04'))]
_MEMBER = {'silver': Decimal('0.02'), 'gold': Decimal('0.05')}


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

    def _unit_price(self, product, qty):
        price = product.base_price
        for min_qty, pct in _VOLUME:
            if qty >= min_qty:
                price = price * (1 - pct)
                break
        price = price * (1 - _MEMBER.get(self.customer.tier, Decimal(0)))
        price = price.quantize(CENT, rounding=ROUND_HALF_UP)
        floor = (product.cost * Decimal('1.10')).quantize(CENT, rounding=ROUND_CEILING)
        return max(price, floor)

    def lines(self):
        """[(sku, qty, unit_price, line_total)] in the order skus were first added."""
        out = []
        for sku, qty in self._qty.items():
            unit = self._unit_price(self.catalog.get(sku), qty)
            out.append((sku, qty, unit, unit * qty))
        return out

    def total(self):
        return sum((line[3] for line in self.lines()), Decimal('0.00'))

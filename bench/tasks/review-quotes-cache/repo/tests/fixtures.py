from decimal import Decimal

from quotes.catalog import Catalog, Product


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def catalog():
    return Catalog([
        Product('DRL-100', 'Cordless drill', 'tools', Decimal('129.00'), Decimal('2.4')),
        Product('GLV-001', 'Work gloves', 'safety', Decimal('8.50'), Decimal('0.2')),
        Product('TAP-050', 'Duct tape', 'consumables', Decimal('4.99'), Decimal('0.3')),
    ])

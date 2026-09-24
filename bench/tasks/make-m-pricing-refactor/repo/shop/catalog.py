from collections import namedtuple
from decimal import Decimal

Product = namedtuple('Product', 'sku name base_price cost')


class UnknownProduct(KeyError):
    pass


def product(sku, name, base_price, cost):
    return Product(sku, name, Decimal(base_price), Decimal(cost))


class Catalog:
    def __init__(self, products=()):
        self._products = {}
        for p in products:
            self.add(p)

    def add(self, p):
        self._products[p.sku] = p

    def get(self, sku):
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownProduct(sku)

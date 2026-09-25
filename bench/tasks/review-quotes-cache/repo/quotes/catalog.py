from dataclasses import dataclass, replace
from decimal import Decimal


class UnknownSku(KeyError):
    pass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    category: str
    base_price: Decimal     # USD list price per unit
    weight_kg: Decimal


class Catalog:
    def __init__(self, products=()):
        self._products = {p.sku: p for p in products}

    def get(self, sku):
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownSku(sku) from None

    def set_price(self, sku, base_price):
        self._products[sku] = replace(self.get(sku), base_price=Decimal(base_price))

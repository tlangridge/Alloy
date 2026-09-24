from shop.catalog import Catalog, product
from shop.customers import Customer
from shop.inventory import Inventory


def setup():
    catalog = Catalog([
        product('MUG', 'Mug', '19.99', '6.10'),
        product('TEA', 'Tea tin', '1.25', '0.40'),
        product('LAMP', 'Desk lamp', '11.00', '10.00'),
        product('PEN', 'Pen', '3.50', '3.33'),
    ])
    inv = Inventory()
    for sku in ('MUG', 'TEA', 'LAMP', 'PEN'):
        inv.receive(sku, 500)
    return catalog, inv


GOLD = Customer('c1', 'gold')
SILVER = Customer('c2', 'silver')
STANDARD = Customer('c3', 'standard')

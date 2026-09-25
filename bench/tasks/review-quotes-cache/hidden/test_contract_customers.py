import unittest
from decimal import Decimal

from quotes.catalog import Catalog, Product
from quotes.customers import Customer
from quotes.service import QuoteService


class Clock:
    now = 50.0

    def __call__(self):
        return self.now


def catalog():
    return Catalog([
        Product('DRL-100', 'Cordless drill', 'tools', Decimal('129.00'), Decimal('2.4')),
        Product('GLV-001', 'Work gloves', 'safety', Decimal('8.50'), Decimal('0.2')),
    ])


PLAIN = Customer('c1', 'US-CA')
ACME = Customer('c2', 'US-CA', contract='ACME-2026')          # 10% off tools
BUILDCO = Customer('c3', 'US-CA', contract='BUILDCO-7')       # 18% off tools


class ContractCustomersTests(unittest.TestCase):
    """A cached quote must equal what a fresh computation returns for the same call."""

    def setUp(self):
        self.catalog = catalog()
        self.clock = Clock()
        self.svc = QuoteService(self.catalog, clock=self.clock)

    def fresh(self, customer, sku, quantity):
        return QuoteService(self.catalog, clock=self.clock).quote(customer, sku, quantity)

    def test_contract_customer_after_list_price_customer(self):
        self.svc.quote(PLAIN, 'DRL-100', 3)
        got = self.svc.quote(ACME, 'DRL-100', 3)
        self.assertEqual(got, self.fresh(ACME, 'DRL-100', 3))
        self.assertEqual(got.unit_price, Decimal('116.10'))

    def test_list_price_customer_after_contract_customer(self):
        self.svc.quote(BUILDCO, 'DRL-100', 1)
        self.assertEqual(self.svc.quote(PLAIN, 'DRL-100', 1).unit_price, Decimal('129.00'))

    def test_two_different_contracts(self):
        self.svc.quote(ACME, 'DRL-100', 1)
        self.assertEqual(self.svc.quote(BUILDCO, 'DRL-100', 1), self.fresh(BUILDCO, 'DRL-100', 1))

    def test_same_contract_still_hits_cache(self):
        self.svc.quote(ACME, 'GLV-001', 4)
        self.svc.quote(Customer('c9', 'US-CA', contract='ACME-2026'), 'GLV-001', 4)
        self.assertEqual(self.svc.computations, 1)


if __name__ == '__main__':
    unittest.main()

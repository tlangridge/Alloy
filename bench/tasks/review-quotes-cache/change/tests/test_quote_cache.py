import unittest
from decimal import Decimal

from quotes.customers import Customer
from quotes.service import CACHE_TTL, QuoteService

from fixtures import FakeClock, catalog

RETAIL_CA = Customer('c1', 'US-CA')
OTHER_RETAIL_CA = Customer('c2', 'US-CA')
WHOLESALE_CA = Customer('c3', 'US-CA', segment='wholesale')
RETAIL_NY = Customer('c4', 'US-NY')
RETAIL_ON_CAD = Customer('c5', 'CA-ON', currency='CAD')


class QuoteCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.catalog = catalog()
        self.svc = QuoteService(self.catalog, clock=self.clock)

    def fresh(self, customer, sku, quantity):
        return QuoteService(self.catalog, clock=self.clock).quote(customer, sku, quantity)

    def test_repeated_request_is_served_from_cache(self):
        first = self.svc.quote(RETAIL_CA, 'DRL-100', 2)
        self.assertIs(self.svc.quote(RETAIL_CA, 'DRL-100', 2), first)
        self.assertEqual(self.svc.computations, 1)

    def test_customers_with_the_same_profile_share_entries(self):
        self.svc.quote(RETAIL_CA, 'DRL-100', 2)
        self.assertEqual(self.svc.quote(OTHER_RETAIL_CA, 'DRL-100', 2), self.fresh(OTHER_RETAIL_CA, 'DRL-100', 2))
        self.assertEqual(self.svc.computations, 1)

    def test_pricing_inputs_get_their_own_entries(self):
        for customer in (RETAIL_CA, WHOLESALE_CA, RETAIL_NY, RETAIL_ON_CAD):
            for quantity in (1, 30):
                with self.subTest(customer=customer.id, quantity=quantity):
                    self.assertEqual(self.svc.quote(customer, 'DRL-100', quantity),
                                     self.fresh(customer, 'DRL-100', quantity))
        self.assertEqual(self.svc.computations, 8)

    def test_entries_expire_after_ttl(self):
        self.svc.quote(RETAIL_CA, 'GLV-001', 5)
        self.clock.now += CACHE_TTL - 1
        self.svc.quote(RETAIL_CA, 'GLV-001', 5)
        self.assertEqual(self.svc.computations, 1)
        self.clock.now += 1
        self.svc.quote(RETAIL_CA, 'GLV-001', 5)
        self.assertEqual(self.svc.computations, 2)

    def test_invalidate_sku_after_price_change(self):
        self.svc.quote(RETAIL_CA, 'DRL-100', 1)
        self.svc.quote(RETAIL_NY, 'DRL-100', 1)
        self.svc.quote(RETAIL_CA, 'GLV-001', 1)
        self.catalog.set_price('DRL-100', '99.00')
        self.assertEqual(self.svc.invalidate_sku('DRL-100'), 2)
        self.assertEqual(self.svc.quote(RETAIL_CA, 'DRL-100', 1).unit_price, Decimal('99.00'))
        self.svc.quote(RETAIL_CA, 'GLV-001', 1)
        self.assertEqual(self.svc.computations, 4)

    def test_invalid_quantity_is_not_cached(self):
        with self.assertRaises(ValueError):
            self.svc.quote(RETAIL_CA, 'DRL-100', 0)
        self.assertEqual(self.svc.computations, 0)


if __name__ == '__main__':
    unittest.main()

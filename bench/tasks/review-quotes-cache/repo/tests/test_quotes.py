import unittest
from decimal import Decimal

from quotes import contracts, pricing
from quotes.catalog import UnknownSku
from quotes.customers import Customer
from quotes.service import QuoteService

from fixtures import FakeClock, catalog

RETAIL_CA = Customer('c1', 'US-CA')


class PricingTests(unittest.TestCase):
    def test_volume_breaks(self):
        self.assertEqual(pricing.volume_factor(24), 1)
        self.assertEqual(pricing.volume_factor(25), Decimal('0.95'))
        self.assertEqual(pricing.volume_factor(100), Decimal('0.90'))

    def test_contract_discounts(self):
        self.assertEqual(contracts.discount_for('ACME-2026', 'tools'), Decimal('0.10'))
        self.assertEqual(contracts.discount_for('ACME-2026', 'consumables'), 0)
        self.assertEqual(contracts.discount_for(None, 'tools'), 0)

    def test_unit_price_combines_segment_volume_and_contract(self):
        product = catalog().get('DRL-100')
        wholesale_acme = Customer('c9', 'US-CA', segment='wholesale', contract='ACME-2026')
        # 129.00 * 0.85 * 0.95 * 0.90 = 93.749... -> 93.75
        self.assertEqual(pricing.unit_price(product, wholesale_acme, 30), Decimal('93.75'))


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.svc = QuoteService(catalog(), clock=FakeClock())

    def test_retail_quote(self):
        q = self.svc.quote(RETAIL_CA, 'DRL-100', 2)
        self.assertEqual((q.unit_price, q.subtotal, q.shipping), (Decimal('129.00'), Decimal('258.00'), Decimal('12.84')))
        self.assertEqual(q.tax, Decimal('19.64'))
        self.assertEqual(q.total, Decimal('290.48'))

    def test_currency_conversion(self):
        q = self.svc.quote(Customer('c2', 'CA-ON', currency='CAD'), 'GLV-001', 10)
        self.assertEqual(q.currency, 'CAD')
        self.assertEqual(q.unit_price, Decimal('11.60'))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            self.svc.quote(RETAIL_CA, 'DRL-100', 0)
        with self.assertRaises(UnknownSku):
            self.svc.quote(RETAIL_CA, 'NOPE', 1)


if __name__ == '__main__':
    unittest.main()

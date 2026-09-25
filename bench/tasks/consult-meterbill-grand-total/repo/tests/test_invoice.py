import unittest
from decimal import Decimal

from meterbill import invoice, promos
from meterbill.money import percent_of, to_money


DOC = {
    'rates': {'api_call': Decimal('0.0004'), 'seat': Decimal('12.5')},
    'promos': {'HALF': {'percent': 50}},
}


class MoneyTests(unittest.TestCase):
    def test_to_money_rounds_half_up(self):
        self.assertEqual(to_money(Decimal('2.345')), Decimal('2.35'))
        self.assertEqual(to_money(Decimal('2.344')), Decimal('2.34'))

    def test_percent_of(self):
        self.assertEqual(percent_of(Decimal('80.00'), 15), Decimal('12.00'))


class InvoiceTests(unittest.TestCase):
    def test_rate_line(self):
        self.assertEqual(invoice.rate_line(1000, Decimal('0.0004')), Decimal('0.40'))
        self.assertEqual(invoice.rate_line(3, Decimal('12.5')), Decimal('37.50'))

    def test_build_without_promo(self):
        inv = invoice.build(DOC, {'id': 'c1', 'usage': {'api_call': 2500, 'seat': 2}})
        self.assertEqual(inv.subtotal, Decimal('26.00'))
        self.assertEqual(inv.total, Decimal('26.00'))

    def test_promo_discount(self):
        discount = promos.discount_for('HALF', Decimal('26.00'), DOC['promos'], redeemed=set())
        self.assertEqual(discount, Decimal('13.00'))

    def test_unknown_promo_is_ignored(self):
        self.assertEqual(promos.discount_for('NOPE', Decimal('26.00'), DOC['promos'], redeemed=set()),
                         Decimal('0'))


if __name__ == '__main__':
    unittest.main()

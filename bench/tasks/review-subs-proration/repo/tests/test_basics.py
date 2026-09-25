import unittest
from datetime import date
from decimal import Decimal

from subs import money, plans
from subs.invoice import Invoice, LineItem
from subs.periods import BillingPeriod, monthly_period


class MoneyTests(unittest.TestCase):
    def test_round_money_is_half_up(self):
        self.assertEqual(money.round_money(Decimal('1.005')), Decimal('1.01'))
        self.assertEqual(money.round_money(Decimal('1.015')), Decimal('1.02'))
        self.assertEqual(money.round_money(Decimal('-1.005')), Decimal('-1.01'))
        self.assertEqual(money.round_money(Decimal('2.0049')), Decimal('2.00'))

    def test_parse_and_fmt(self):
        self.assertEqual(money.parse('12.30'), Decimal('12.30'))
        with self.assertRaises(ValueError):
            money.parse('1.001')
        self.assertEqual(money.fmt(Decimal('-1234.5'), 'USD'), '-USD 1,234.50')


class PeriodTests(unittest.TestCase):
    def test_simple_period(self):
        self.assertEqual(monthly_period(15, date(2026, 4, 20)), BillingPeriod(date(2026, 4, 15), date(2026, 5, 15)))
        self.assertEqual(monthly_period(15, date(2026, 4, 14)), BillingPeriod(date(2026, 3, 15), date(2026, 4, 15)))

    def test_clamped_anchor(self):
        self.assertEqual(monthly_period(31, date(2026, 2, 10)), BillingPeriod(date(2026, 1, 31), date(2026, 2, 28)))
        self.assertEqual(monthly_period(31, date(2026, 3, 1)), BillingPeriod(date(2026, 2, 28), date(2026, 3, 31)))

    def test_year_boundary_and_days(self):
        period = monthly_period(20, date(2026, 1, 5))
        self.assertEqual(period, BillingPeriod(date(2025, 12, 20), date(2026, 1, 20)))
        self.assertEqual(period.days, 31)
        self.assertIn(date(2026, 1, 19), period)
        self.assertNotIn(date(2026, 1, 20), period)


class InvoiceTests(unittest.TestCase):
    def test_total(self):
        inv = Invoice('cust-1', 'USD')
        inv.add(LineItem('Team', plans.get('team').monthly_price))
        inv.add(LineItem('Credit', Decimal('-5.00'), 'credit'))
        self.assertEqual(inv.total, Decimal('24.99'))

    def test_amounts_must_be_cents(self):
        inv = Invoice('cust-1', 'USD')
        for bad in (Decimal('1.005'), Decimal('1.5'), 1.5, Decimal('NaN')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    inv.add(LineItem('x', bad))


if __name__ == '__main__':
    unittest.main()

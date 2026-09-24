import unittest
from datetime import date
from decimal import Decimal

from subs.invoice import Invoice
from subs.periods import BillingPeriod
from subs.plans import get
from subs.proration import apply_plan_change, plan_change_lines

STARTER, TEAM, CLASSIC = get('starter'), get('team'), get('classic')
APRIL = BillingPeriod(date(2026, 4, 1), date(2026, 5, 1))          # 30 days
FEBRUARY = BillingPeriod(date(2026, 2, 1), date(2026, 3, 1))       # 28 days


def amounts(lines):
    return [line.amount for line in lines]


class HalfCentTiesRoundUpTests(unittest.TestCase):
    """Exact half-cent prorations must round half-up (money.round_money), not half-even."""

    def test_credit_on_exact_half_cent(self):
        # 9.99 * 5/30 = 1.665 exactly -> 1.67 ; 29.99 * 5/30 = 4.99833 -> 5.00
        lines = plan_change_lines(STARTER, TEAM, APRIL, date(2026, 4, 26))
        self.assertEqual(amounts(lines), [Decimal('-1.67'), Decimal('5.00')])

    def test_charge_on_exact_half_cent(self):
        # 29.99 * 25/30 = 24.99166 -> 24.99 ; 9.99 * 25/30 = 8.325 exactly -> 8.33
        lines = plan_change_lines(TEAM, STARTER, APRIL, date(2026, 4, 6))
        self.assertEqual(amounts(lines), [Decimal('-24.99'), Decimal('8.33')])

    def test_legacy_plan_half_period(self):
        # 12.45 * 15/30 = 6.225 exactly -> 6.23 ; 29.99 * 15/30 = 14.995 -> 15.00
        lines = plan_change_lines(CLASSIC, TEAM, APRIL, date(2026, 4, 16))
        self.assertEqual(amounts(lines), [Decimal('-6.23'), Decimal('15.00')])

    def test_february_period(self):
        # 12.45 * 14/28 = 6.225 exactly -> 6.23
        lines = plan_change_lines(STARTER, CLASSIC, FEBRUARY, date(2026, 2, 15))
        self.assertEqual(amounts(lines)[1], Decimal('6.23'))

    def test_invoice_net(self):
        invoice = Invoice('cust-9', 'USD')
        self.assertEqual(apply_plan_change(invoice, STARTER, TEAM, APRIL, date(2026, 4, 26)), Decimal('3.33'))
        self.assertEqual(invoice.total, Decimal('3.33'))


if __name__ == '__main__':
    unittest.main()

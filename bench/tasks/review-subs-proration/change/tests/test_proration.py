import unittest
from datetime import date
from decimal import Decimal

from subs.invoice import Invoice
from subs.periods import BillingPeriod, monthly_period
from subs.plans import get
from subs.proration import apply_plan_change, plan_change_lines, remaining_days

STARTER, TEAM, BUSINESS, TEAM_EU = get('starter'), get('team'), get('business'), get('team-eu')
JANUARY = BillingPeriod(date(2026, 1, 1), date(2026, 2, 1))          # 31 days


def amounts(lines):
    return [line.amount for line in lines]


class RemainingDaysTests(unittest.TestCase):
    def test_counts_change_day_but_not_period_end(self):
        self.assertEqual(remaining_days(JANUARY, date(2026, 1, 1)), 31)
        self.assertEqual(remaining_days(JANUARY, date(2026, 1, 15)), 17)
        self.assertEqual(remaining_days(JANUARY, date(2026, 1, 31)), 1)

    def test_outside_period(self):
        for day in (date(2025, 12, 31), date(2026, 2, 1)):
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    remaining_days(JANUARY, day)


class PlanChangeTests(unittest.TestCase):
    def test_upgrade_mid_period(self):
        lines = plan_change_lines(TEAM, BUSINESS, JANUARY, date(2026, 1, 15))
        # 29.99 * 17/31 = 16.4461..., 49.99 * 17/31 = 27.4138...
        self.assertEqual(amounts(lines), [Decimal('-16.45'), Decimal('27.41')])
        self.assertEqual([line.kind for line in lines], ['proration', 'proration'])
        self.assertEqual(lines[0].description, 'Unused time on Team (17 of 31 days)')
        self.assertEqual(lines[1].description, 'Remaining time on Business (17 of 31 days)')

    def test_downgrade_nets_to_a_credit(self):
        lines = plan_change_lines(BUSINESS, STARTER, JANUARY, date(2026, 1, 22))
        # 49.99 * 10/31 = 16.1258..., 9.99 * 10/31 = 3.2225...
        self.assertEqual(amounts(lines), [Decimal('-16.13'), Decimal('3.22')])

    def test_change_on_first_day_is_a_full_swap(self):
        lines = plan_change_lines(STARTER, TEAM, JANUARY, date(2026, 1, 1))
        self.assertEqual(amounts(lines), [Decimal('-9.99'), Decimal('29.99')])

    def test_short_february_period(self):
        february = monthly_period(1, date(2026, 2, 10))
        lines = plan_change_lines(TEAM, BUSINESS, february, date(2026, 2, 10))
        # 19 of 28 days: 29.99 * 19/28 = 20.3503..., 49.99 * 19/28 = 33.9217...
        self.assertEqual(amounts(lines), [Decimal('-20.35'), Decimal('33.92')])

    def test_same_plan_is_a_no_op(self):
        self.assertEqual(plan_change_lines(TEAM, TEAM, JANUARY, date(2026, 1, 9)), [])

    def test_currency_mismatch(self):
        with self.assertRaises(ValueError):
            plan_change_lines(TEAM, TEAM_EU, JANUARY, date(2026, 1, 9))

    def test_amounts_have_cent_precision(self):
        for day in range(1, 32):
            for old, new in ((STARTER, TEAM), (TEAM, BUSINESS), (BUSINESS, STARTER)):
                for line in plan_change_lines(old, new, JANUARY, date(2026, 1, day)):
                    self.assertEqual(line.amount.as_tuple().exponent, -2)


class ApplyTests(unittest.TestCase):
    def test_lines_added_and_net_returned(self):
        invoice = Invoice('cust-1', 'USD')
        net = apply_plan_change(invoice, TEAM, BUSINESS, JANUARY, date(2026, 1, 15))
        self.assertEqual(net, Decimal('10.96'))
        self.assertEqual(invoice.total, Decimal('10.96'))
        self.assertEqual(len(invoice.lines), 2)

    def test_no_change_adds_nothing(self):
        invoice = Invoice('cust-1', 'USD')
        self.assertEqual(apply_plan_change(invoice, TEAM, TEAM, JANUARY, date(2026, 1, 15)), Decimal('0.00'))
        self.assertEqual(invoice.lines, [])

    def test_invoice_currency_must_match(self):
        with self.assertRaises(ValueError):
            apply_plan_change(Invoice('cust-1', 'EUR'), TEAM, BUSINESS, JANUARY, date(2026, 1, 15))


if __name__ == '__main__':
    unittest.main()

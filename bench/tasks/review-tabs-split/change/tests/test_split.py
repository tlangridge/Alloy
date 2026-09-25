import unittest

from tabs.ledger import Ledger
from tabs.split import split_cents


class SplitCentsTests(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(split_cents(900, {'ana': 1, 'ben': 1, 'cy': 1}), {'ana': 300, 'ben': 300, 'cy': 300})

    def test_odd_cent_goes_to_first_name_on_ties(self):
        self.assertEqual(split_cents(100, {'cy': 1, 'ana': 1, 'ben': 1}), {'cy': 33, 'ana': 34, 'ben': 33})
        self.assertEqual(split_cents(101, {'cy': 1, 'ana': 1, 'ben': 1}), {'cy': 33, 'ana': 34, 'ben': 34})

    def test_largest_remainder_wins(self):
        # exact: ana 3.3333, ben 6.6667 -> floors 3 and 6, ben has the larger remainder
        self.assertEqual(split_cents(10, {'ana': 1, 'ben': 2}), {'ana': 3, 'ben': 7})

    def test_weights(self):
        self.assertEqual(split_cents(1000, {'ana': 1, 'ben': 1, 'cy': 2}), {'ana': 250, 'ben': 250, 'cy': 500})

    def test_zero_weight_gets_nothing(self):
        self.assertEqual(split_cents(7, {'ana': 0, 'ben': 1, 'cy': 1}), {'ana': 0, 'ben': 4, 'cy': 3})

    def test_refund_mirrors_charge(self):
        weights = {'ana': 3, 'ben': 5, 'cy': 7}
        charge = split_cents(1001, weights)
        self.assertEqual(split_cents(-1001, weights), {k: -v for k, v in charge.items()})

    def test_zero_total(self):
        self.assertEqual(split_cents(0, {'ana': 1, 'ben': 2}), {'ana': 0, 'ben': 0})

    def test_sum_is_exact(self):
        weights = {'a': 7, 'b': 11, 'c': 13, 'd': 0, 'e': 1}
        for total in range(-500, 501, 7):
            with self.subTest(total=total):
                self.assertEqual(sum(split_cents(total, weights).values()), total)

    def test_validation(self):
        for total, weights, error in (
            (1.5, {'a': 1}, TypeError),
            (True, {'a': 1}, TypeError),
            (10, {}, ValueError),
            (10, {'a': 0, 'b': 0}, ValueError),
            (10, {'a': -1, 'b': 2}, ValueError),
            (10, {'a': 1.0}, TypeError),
            (10, {'a': True}, TypeError),
            (10, {1: 1}, TypeError),
        ):
            with self.subTest(total=total, weights=weights):
                with self.assertRaises(error):
                    split_cents(total, weights)


class LedgerSplitTests(unittest.TestCase):
    def test_add_split_expense(self):
        ledger = Ledger(['ana', 'ben', 'cy'])
        expense = ledger.add_split_expense('ana', 1000, {'ana': 1, 'ben': 1, 'cy': 1}, 'taxi')
        self.assertEqual(expense.shares, {'ana': 334, 'ben': 333, 'cy': 333})
        self.assertEqual(ledger.balances(), {'ana': 666, 'ben': -333, 'cy': -333})
        self.assertEqual(sum(ledger.balances().values()), 0)

    def test_non_member_rejected(self):
        with self.assertRaises(ValueError):
            Ledger(['ana']).add_split_expense('ana', 100, {'ana': 1, 'zed': 1})


if __name__ == '__main__':
    unittest.main()
